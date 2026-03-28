"""Tests for runtime refresh queueing, overlay precedence, and self-heal."""

import os
import subprocess
import time

from dotscope.cli import main
from dotscope.composer import compose
from dotscope.context import parse_context
from dotscope.ingest import ingest
from dotscope.parser import parse_scope_file
from dotscope.passes.incremental import incremental_update
from dotscope.refresh import (
    enqueue_commit_refresh,
    enqueue_repo_refresh,
    enqueue_scope_refresh,
    ensure_resolution_freshness,
    load_refresh_queue,
    run_refresh_queue,
)
from dotscope.runtime_overlay import (
    runtime_index_path,
    runtime_scope_path,
    write_runtime_scope,
)
from dotscope.storage.git_hooks import hook_status, install_hook, uninstall_hook


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=False)


def _git_commit(path, msg):
    subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", msg, "--allow-empty"], cwd=str(path), capture_output=True, check=False)


def _head_commit(path):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


class TestRuntimeOverlay:
    def test_compose_prefers_runtime_overlay(self, tmp_project):
        config = parse_scope_file(str(tmp_project / "auth" / ".scope"))
        config.context = parse_context("Runtime auth context only.")
        write_runtime_scope(str(tmp_project), config, scope_name="auth")

        result = compose("auth", root=str(tmp_project), follow_related=False)

        assert "Runtime auth context only." in result.context

    def test_cli_match_uses_runtime_overlay_keywords(self, tmp_project, capsys, monkeypatch):
        config = parse_scope_file(str(tmp_project / "auth" / ".scope"))
        config.description = "OAuth refresh session flow"
        config.tags = ["oauth-refresh"]
        write_runtime_scope(str(tmp_project), config, scope_name="auth")

        monkeypatch.chdir(tmp_project)
        main(["match", "fix oauth refresh issue"])
        output = capsys.readouterr().out

        assert "auth" in output.lower()

    def test_manual_ingest_syncs_runtime_overlay(self, tmp_path):
        _git_init(tmp_path)

        mod = tmp_path / "mylib"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "core.py").write_text("def run():\n    return True\n")

        ingest(str(tmp_path), mine_history=False, dry_run=False)

        assert (mod / ".scope").exists()
        assert os.path.exists(runtime_scope_path(str(tmp_path), "mylib/.scope"))
        assert os.path.exists(runtime_index_path(str(tmp_path)))

    def test_incremental_updates_runtime_overlay_without_dirtying_tracked_scope(self, tmp_path):
        _git_init(tmp_path)

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "handler.py").write_text("def login():\n    return True\n")
        (auth / ".scope").write_text(
            "description: Auth\n"
            "includes:\n"
            "  - auth/handler.py\n"
        )

        tracked_before = (auth / ".scope").read_text()
        (auth / "tokens.py").write_text("def refresh():\n    return True\n")

        incremental_update(
            str(tmp_path),
            changed_files=["auth/tokens.py"],
            added_files=["auth/tokens.py"],
            deleted_files=[],
            commit_hash="abc123",
        )

        assert (auth / ".scope").read_text() == tracked_before
        runtime_config = parse_scope_file(runtime_scope_path(str(tmp_path), "auth/.scope"))
        assert "auth/tokens.py" in runtime_config.includes


class TestRefreshQueue:
    def test_scope_jobs_dedupe(self, tmp_path):
        enqueue_scope_refresh(str(tmp_path), ["auth"], reason="first")
        enqueue_scope_refresh(str(tmp_path), ["auth"], reason="second")

        queue = load_refresh_queue(str(tmp_path))
        assert len(queue) == 1
        assert queue[0]["kind"] == "scope"
        assert queue[0]["targets"] == ["auth"]

    def test_repo_job_supersedes_scope_jobs(self, tmp_path):
        enqueue_scope_refresh(str(tmp_path), ["auth"], reason="scope")
        enqueue_repo_refresh(str(tmp_path), reason="repo")

        queue = load_refresh_queue(str(tmp_path))
        assert len(queue) == 1
        assert queue[0]["kind"] == "repo"

    def test_worker_respects_refresh_lock(self, tmp_path):
        enqueue_scope_refresh(str(tmp_path), ["auth"], reason="scope")
        lock_path = tmp_path / ".dotscope" / "refresh.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("busy")

        assert run_refresh_queue(str(tmp_path), drain=True) is False

    def test_modify_only_commit_queues_scope_refresh(self, tmp_path):
        _git_init(tmp_path)

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "handler.py").write_text("def login():\n    return True\n")
        (auth / ".scope").write_text(
            "description: Auth\n"
            "includes:\n"
            "  - auth/\n"
        )
        _git_commit(tmp_path, "initial")

        (auth / "handler.py").write_text("def login():\n    return False\n")
        _git_commit(tmp_path, "modify handler")

        enqueue_commit_refresh(str(tmp_path), _head_commit(tmp_path))
        queue = load_refresh_queue(str(tmp_path))

        assert len(queue) == 1
        assert queue[0]["kind"] == "scope"
        assert queue[0]["targets"] == ["auth"]

    def test_added_file_commit_queues_repo_refresh(self, tmp_path):
        _git_init(tmp_path)

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "handler.py").write_text("def login():\n    return True\n")
        (auth / ".scope").write_text(
            "description: Auth\n"
            "includes:\n"
            "  - auth/\n"
        )
        _git_commit(tmp_path, "initial")

        (auth / "tokens.py").write_text("def refresh():\n    return True\n")
        _git_commit(tmp_path, "add file")

        enqueue_commit_refresh(str(tmp_path), _head_commit(tmp_path))
        queue = load_refresh_queue(str(tmp_path))

        assert len(queue) == 1
        assert queue[0]["kind"] == "repo"


class TestResolveFreshnessGate:
    def test_stale_directory_scope_self_heals_inline(self, tmp_project):
        scope_path = tmp_project / "auth" / ".scope"
        old_time = time.time() - (40 * 86400)
        os.utime(scope_path, (old_time, old_time))
        (tmp_project / "auth" / "handler.py").write_text(
            "from models.user import User\n"
            "def login():\n"
            "    return User\n"
        )

        freshness = ensure_resolution_freshness(str(tmp_project), "auth", timeout_seconds=5.0)

        assert freshness["state"] == "self_healed"
        assert freshness["job_kind"] == "scope"
        assert os.path.exists(runtime_scope_path(str(tmp_project), "auth/.scope"))

    def test_virtual_scope_timeout_falls_back_and_queues_repo(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "handler.py").write_text("def login():\n    return True\n")

        virtual = tmp_path / "virtual" / "reporting"
        virtual.mkdir(parents=True)
        scope_path = virtual / ".scope"
        scope_path.write_text(
            "description: Reporting\n"
            "includes:\n"
            "  - auth/handler.py\n"
        )
        old_time = time.time() - (40 * 86400)
        os.utime(scope_path, (old_time, old_time))

        monkeypatch.setattr("dotscope.refresh._wait_for_repo_refresh", lambda root, timeout_seconds: False)
        monkeypatch.setattr("dotscope.refresh.kick_refresh_worker", lambda root: None)

        freshness = ensure_resolution_freshness(str(tmp_path), "virtual/reporting")

        assert freshness["state"] == "stale_fallback"
        assert freshness["job_kind"] == "repo"
        queue = load_refresh_queue(str(tmp_path))
        assert len(queue) == 1
        assert queue[0]["kind"] == "repo"


class TestRefreshHooks:
    def test_install_status_and_uninstall_cover_refresh_hooks(self, tmp_path):
        _git_init(tmp_path)

        result = install_hook(str(tmp_path))
        status = hook_status(str(tmp_path))

        assert "post-commit:" in result
        assert "post-checkout:" in result
        assert "post-merge:" in result
        assert "post-checkout: installed" in status
        assert "post-merge: installed" in status

        checkout_hook = (tmp_path / ".git" / "hooks" / "post-checkout").read_text()
        assert '$3' in checkout_hook or 'sys.argv[3]' in checkout_hook

        removed = uninstall_hook(str(tmp_path))
        assert removed
