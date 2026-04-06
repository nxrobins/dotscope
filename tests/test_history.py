"""Tests for git history mining."""

import os
import subprocess
import pytest
from dotscope.passes.history_miner import analyze_history, format_history_summary


def _git_init(path):
    """Initialize a git repo with some commits."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)


def _git_commit(path, message, files):
    """Stage files and commit."""
    for f in files:
        subprocess.run(["git", "add", f], cwd=str(path), capture_output=True)
    subprocess.run(["git", "commit", "-m", message, "--allow-empty"], cwd=str(path), capture_output=True)


class TestHistory:
    def test_no_git_returns_empty(self, tmp_path):
        result = analyze_history(str(tmp_path))
        assert result.commits_analyzed == 0

    def test_basic_history(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "a.py").write_text("# a\n")
        _git_commit(tmp_path, "add a", ["a.py"])

        (tmp_path / "b.py").write_text("# b\n")
        _git_commit(tmp_path, "add b", ["b.py"])

        result = analyze_history(str(tmp_path))
        assert result.commits_analyzed >= 2
        assert "a.py" in result.file_histories

    def test_hotspots(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "hot.py").write_text("v1\n")
        _git_commit(tmp_path, "v1", ["hot.py"])

        for i in range(5):
            (tmp_path / "hot.py").write_text(f"v{i+2}\n")
            _git_commit(tmp_path, f"update {i}", ["hot.py"])

        result = analyze_history(str(tmp_path))
        assert len(result.hotspots) > 0
        assert result.hotspots[0][0] == "hot.py"

    def test_recent_summaries(self, tmp_path):
        _git_init(tmp_path)
        mod = tmp_path / "auth"
        mod.mkdir()
        (mod / "handler.py").write_text("# handler\n")
        _git_commit(tmp_path, "add auth handler", ["auth/handler.py"])

        result = analyze_history(str(tmp_path))
        assert "auth" in result.recent_summaries
        assert any("handler" in msg for msg in result.recent_summaries["auth"])

    def test_format_summary(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "main.py").write_text("# main\n")
        _git_commit(tmp_path, "init", ["main.py"])

        result = analyze_history(str(tmp_path))
        summary = format_history_summary(result)
        assert "Git History" in summary
