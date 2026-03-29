"""Tests for the ingest pipeline."""

import os
import subprocess
import pytest
from dotscope.ingest import (
    ingest,
    format_ingest_report,
    _is_cross_module,
    _find_hub_discoveries,
    _find_volatility_surprises,
    _extract_discoveries,
    _extract_validation,
)
from dotscope.passes.incremental import incremental_update
from dotscope.storage.incremental_state import (
    get_scope_refresh_epoch,
    load_incremental_state,
    save_incremental_state,
)


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)


def _git_commit(path, msg="commit"):
    subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg, "--allow-empty"],
        cwd=str(path), capture_output=True,
    )


class TestIngest:
    def test_ingest_dry_run(self, tmp_path):
        _git_init(tmp_path)

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "__init__.py").write_text("")
        (auth / "handler.py").write_text("def login(): pass\n")

        api = tmp_path / "api"
        api.mkdir()
        (api / "__init__.py").write_text("")
        (api / "routes.py").write_text("from auth.handler import login\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)

        assert len(plan.scopes) >= 2
        assert not (auth / ".scope").exists()  # dry run shouldn't write

    def test_ingest_writes_files(self, tmp_path):
        _git_init(tmp_path)

        mod = tmp_path / "mylib"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "core.py").write_text("def main(): pass\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=False)

        assert (mod / ".scope").exists()
        assert (tmp_path / ".scopes").exists()

    def test_ingest_skips_existing_scopes(self, tmp_path):
        _git_init(tmp_path)

        mod = tmp_path / "existing"
        mod.mkdir()
        (mod / "main.py").write_text("")
        (mod / ".scope").write_text("description: Already here\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=False)

        # Should not overwrite
        content = (mod / ".scope").read_text()
        assert "Already here" in content

    def test_ingest_detects_cross_module_deps(self, tmp_path):
        _git_init(tmp_path)

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "__init__.py").write_text("")
        (auth / "handler.py").write_text("from models.user import User\n")

        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("")
        (models / "user.py").write_text("class User: pass\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)

        auth_scope = next((s for s in plan.scopes if s.directory == "auth"), None)
        assert auth_scope is not None
        # Should detect models as a dependency
        assert any("models" in inc for inc in auth_scope.config.includes)

    def test_format_report_discovery_sections(self, tmp_path):
        """Report should have header, Created section, and usage hints."""
        _git_init(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)
        report = format_ingest_report(plan)
        assert "scanned" in report
        assert "\U0001f4c1 Created" in report
        assert "dotscope resolve" in report

    def test_ingest_builds_index(self, tmp_path):
        _git_init(tmp_path)

        for name in ("auth", "api", "models"):
            d = tmp_path / name
            d.mkdir()
            (d / "__init__.py").write_text("")
            (d / "core.py").write_text("")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)
        assert plan.index is not None
        assert len(plan.index.scopes) >= 3

    def test_ingest_survives_non_utf8_source(self, tmp_path):
        _git_init(tmp_path)

        mod = tmp_path / "legacy"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "main.py").write_bytes(
            b"# Caf\xe9\n"
            b"def run():\n"
            b"    return 1\n"
        )

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)

        assert any(scope.directory == "legacy" for scope in plan.scopes)

    def test_virtual_scope_bookkeeping_is_consistent(self, tmp_path):
        _git_init(tmp_path)

        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("")
        (models / "user.py").write_text("class User: pass\n")

        for name in ("auth", "api", "admin"):
            d = tmp_path / name
            d.mkdir()
            (d / "__init__.py").write_text("")
            (d / "handler.py").write_text("from models.user import User\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)

        virtual_scope = next(
            scope for scope in plan.scopes
            if scope.directory == "virtual/user_lifecycle"
        )
        assert virtual_scope.config.path.endswith("virtual/user_lifecycle/.scope")
        assert plan.index.scopes["virtual/user_lifecycle"].path == "virtual/user_lifecycle/.scope"

    def test_full_ingest_marks_existing_scope_refreshed(self, tmp_path):
        _git_init(tmp_path)

        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "main.py").write_text("x = 1\n")
        (existing / ".scope").write_text(
            "description: Existing\n"
            "includes:\n"
            "  - existing/\n"
        )

        ingest(str(tmp_path), mine_history=False, dry_run=False)

        state = load_incremental_state(str(tmp_path))
        assert "existing/.scope" in state.scope_refresh_timestamps

    def test_incremental_refreshes_directory_and_virtual_scope(self, tmp_path):
        _git_init(tmp_path)

        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("")
        (models / "user.py").write_text("class User: pass\n")

        for name in ("auth", "api", "admin"):
            d = tmp_path / name
            d.mkdir()
            (d / "__init__.py").write_text("")
            (d / "handler.py").write_text("from models.user import User\n")

        ingest(str(tmp_path), mine_history=False, dry_run=False)

        state = load_incremental_state(str(tmp_path))
        old_refresh = "2000-01-01T00:00:00Z"
        state.scope_refresh_timestamps["auth/.scope"] = old_refresh
        state.scope_refresh_timestamps["virtual/user_lifecycle/.scope"] = old_refresh
        save_incremental_state(str(tmp_path), state)

        incremental_update(
            str(tmp_path),
            changed_files=["auth/handler.py"],
            added_files=[],
            deleted_files=[],
            commit_hash="abc12345",
        )

        refreshed_state = load_incremental_state(str(tmp_path))
        assert get_scope_refresh_epoch(str(tmp_path), "auth/.scope", refreshed_state) > 0
        assert get_scope_refresh_epoch(
            str(tmp_path),
            "virtual/user_lifecycle/.scope",
            refreshed_state,
        ) > get_scope_refresh_epoch(
            str(tmp_path),
            "virtual/user_lifecycle/.scope",
            state,
        )


class TestIngestPlanStructuredData:
    """Verify that ingest() populates structured data on the plan."""

    def test_repo_token_stats(self, tmp_path):
        _git_init(tmp_path)
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "core.py").write_text("x = 1\n" * 50)

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)
        assert plan.total_repo_files > 0
        assert plan.total_repo_tokens > 0
        assert plan.graph is not None

    def test_history_stored_on_plan(self, tmp_path):
        _git_init(tmp_path)
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "core.py").write_text("x = 1\n")
        _git_commit(tmp_path, "initial")

        plan = ingest(str(tmp_path), mine_history=True, dry_run=True)
        assert plan.history is not None
        assert plan.history.commits_analyzed >= 0


class TestContextPriority:
    """Verify the new context priority order and TODO elimination."""

    def test_context_never_has_todo(self, tmp_path):
        _git_init(tmp_path)
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "core.py").write_text("def main(): pass\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)
        for ps in plan.scopes:
            assert "TODO" not in ps.config.context_str

    def test_empty_module_gets_structural_summary(self, tmp_path):
        """Modules with zero docs should get a graph-derived summary, not TODO."""
        _git_init(tmp_path)
        mod = tmp_path / "bare"
        mod.mkdir()
        (mod / "a.py").write_text("x = 1\n")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)
        bare_scope = next(
            (s for s in plan.scopes if s.directory == "bare"), None
        )
        if bare_scope:
            ctx = bare_scope.config.context_str
            assert "TODO" not in ctx
            # Should have structural info instead
            assert "module" in ctx.lower() or "files" in ctx.lower() or "cohesion" in ctx.lower()


class TestDiscoveryHelpers:
    """Unit tests for the discovery extraction functions."""

    def test_is_cross_module(self):
        assert _is_cross_module("auth/handler.py", "models/user.py")
        assert not _is_cross_module("auth/handler.py", "auth/utils.py")
        assert not _is_cross_module("root.py", "other.py")  # no directories

    def test_find_hub_discoveries_empty_graph(self):
        from dotscope.graph import DependencyGraph
        graph = DependencyGraph(root="/tmp")
        assert _find_hub_discoveries(graph) == []

    def test_find_volatility_surprises_empty_history(self):
        from dotscope.history import HistoryAnalysis
        history = HistoryAnalysis()
        assert _find_volatility_surprises(history) == []

    def test_extract_discoveries_no_data(self):
        """With no history/graph, discoveries should be empty."""
        plan = _make_empty_plan()
        assert _extract_discoveries(plan) == []

    def test_extract_validation_no_backtest(self):
        """With no backtest, validation should be empty."""
        plan = _make_empty_plan()
        assert _extract_validation(plan) == []


def _make_empty_plan():
    """Create a minimal IngestPlan for testing extractors."""
    from dotscope.ingest import IngestPlan
    return IngestPlan(root="/tmp")
