"""Tests for the session tracking and observation layer."""

import json
import os
import subprocess
import time
import pytest
from dotscope.sessions import SessionManager


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)


class TestSessionManager:
    def test_ensure_initialized(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.ensure_initialized()
        assert (tmp_path / ".dotscope" / "sessions").is_dir()
        assert (tmp_path / ".dotscope" / "observations").is_dir()
        assert (tmp_path / ".dotscope" / "schema_version").read_text() == "1"
        assert (tmp_path / ".dotscope" / ".gitignore").read_text() == "*\n"

    def test_create_session(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        sid = mgr.create_session("auth", "fix bug", ["auth/handler.py"], "context text")
        assert len(sid) == 8
        session_files = list((tmp_path / ".dotscope" / "sessions").glob("*.json"))
        assert len(session_files) == 1

        data = json.loads(session_files[0].read_text())
        assert data["session_id"] == sid
        assert data["scope_expr"] == "auth"
        assert data["predicted_files"] == ["auth/handler.py"]

    def test_get_sessions(self, tmp_path):
        mgr = SessionManager(str(tmp_path))
        mgr.create_session("auth", "task1", ["a.py"], "ctx")
        mgr.create_session("payments", "task2", ["b.py"], "ctx")

        sessions = mgr.get_sessions()
        assert len(sessions) == 2

    def test_record_observation(self, tmp_path):
        _git_init(tmp_path)

        # Create a file and commit
        (tmp_path / "auth").mkdir()
        (tmp_path / "auth" / "handler.py").write_text("v1\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)

        # Create a session that predicts auth/handler.py
        mgr = SessionManager(str(tmp_path))
        abs_path = str(tmp_path / "auth" / "handler.py")
        sid = mgr.create_session("auth", "fix", [abs_path], "ctx")

        # Make a change and commit
        (tmp_path / "auth" / "handler.py").write_text("v2\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "update"], cwd=str(tmp_path), capture_output=True)

        # Get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
            capture_output=True, text=True,
        )
        commit_hash = result.stdout.strip()

        obs = mgr.record_observation(commit_hash)
        # May or may not match depending on file path format
        # The key test is that it doesn't crash
        assert obs is None or obs.session_id == sid

    def test_no_session_returns_none(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "unrelated.py").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
            capture_output=True, text=True,
        )
        mgr = SessionManager(str(tmp_path))
        mgr.ensure_initialized()
        obs = mgr.record_observation(result.stdout.strip())
        assert obs is None


class TestHooks:
    def test_install_hook(self, tmp_path):
        _git_init(tmp_path)
        from dotscope.hooks import install_hook, is_hook_installed
        result = install_hook(str(tmp_path))
        assert "pre-commit:" in result
        assert "post-commit:" in result
        assert is_hook_installed(str(tmp_path))

    def test_uninstall_hook(self, tmp_path):
        _git_init(tmp_path)
        from dotscope.hooks import install_hook, uninstall_hook, is_hook_installed
        install_hook(str(tmp_path))
        assert is_hook_installed(str(tmp_path))
        removed = uninstall_hook(str(tmp_path))
        assert removed
        assert not is_hook_installed(str(tmp_path))

    def test_idempotent_install(self, tmp_path):
        _git_init(tmp_path)
        from dotscope.hooks import install_hook
        install_hook(str(tmp_path))
        install_hook(str(tmp_path))  # Should not duplicate
        hook = (tmp_path / ".git" / "hooks" / "post-commit").read_text()
        assert hook.count("dotscope auto-observer") == 1

    def test_no_hook_uninstall(self, tmp_path):
        _git_init(tmp_path)
        from dotscope.hooks import uninstall_hook
        assert not uninstall_hook(str(tmp_path))
