"""Tests for scope backtesting."""

import os
import subprocess
import pytest
from dotscope.passes.backtest import backtest_scopes, auto_correct_scope, format_backtest_report
from dotscope.models import ScopeConfig, BacktestResult, MissingSuggestion
from dotscope.context import parse_context


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)


def _git_commit(path, message, files):
    for f in files:
        subprocess.run(["git", "add", f], cwd=str(path), capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(path), capture_output=True)


class TestBacktest:
    def test_no_git_returns_empty(self, tmp_path):
        scope = ScopeConfig(path=str(tmp_path / "test/.scope"), description="Test")
        report = backtest_scopes(str(tmp_path), [scope])
        assert report.total_commits == 0

    def test_perfect_recall(self, tmp_path):
        _git_init(tmp_path)
        mod = tmp_path / "auth"
        mod.mkdir()
        (mod / "handler.py").write_text("v1\n")
        _git_commit(tmp_path, "add handler", ["auth/handler.py"])

        (mod / "handler.py").write_text("v2\n")
        _git_commit(tmp_path, "update handler", ["auth/handler.py"])

        scope = ScopeConfig(
            path=str(mod / ".scope"),
            description="Auth",
            includes=["auth/"],
        )
        report = backtest_scopes(str(tmp_path), [scope], n_commits=10)
        auth_result = next((r for r in report.results if "auth" in r.scope_path), None)
        assert auth_result is not None
        assert auth_result.recall == 1.0

    def test_detects_missing_includes(self, tmp_path):
        _git_init(tmp_path)
        mod = tmp_path / "auth"
        mod.mkdir()
        (mod / "handler.py").write_text("v1\n")

        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "utils.py").write_text("v1\n")

        _git_commit(tmp_path, "init", ["auth/handler.py", "shared/utils.py"])

        # Commit that touches both auth and shared
        (mod / "handler.py").write_text("v2\n")
        (shared / "utils.py").write_text("v2\n")
        _git_commit(tmp_path, "update both", ["auth/handler.py", "shared/utils.py"])

        (mod / "handler.py").write_text("v3\n")
        (shared / "utils.py").write_text("v3\n")
        _git_commit(tmp_path, "update both again", ["auth/handler.py", "shared/utils.py"])

        scope = ScopeConfig(
            path=str(mod / ".scope"),
            description="Auth",
            includes=["auth/"],
        )
        report = backtest_scopes(str(tmp_path), [scope], n_commits=10)
        auth_result = next((r for r in report.results if "auth" in r.scope_path), None)
        assert auth_result is not None
        assert auth_result.recall < 1.0
        assert any("shared/utils.py" in m.path for m in auth_result.missing_includes)

    def test_auto_correct(self):
        scope = ScopeConfig(
            path="/fake/.scope",
            description="Test",
            includes=["auth/"],
        )
        result = BacktestResult(
            scope_path="/fake/.scope",
            total_commits=10,
            fully_covered=7,
            recall=0.7,
            missing_includes=[
                MissingSuggestion(path="shared/utils.py", appearances=3),
            ],
        )
        updated, changed = auto_correct_scope(scope, result, "/fake")
        assert changed
        assert "shared/utils.py" in updated.includes

    def test_format_report(self):
        report = type("R", (), {
            "total_commits": 50,
            "overall_recall": 0.92,
            "results": [
                BacktestResult(
                    scope_path="/project/auth/.scope",
                    total_commits=30, fully_covered=28, recall=0.933,
                    missing_includes=[MissingSuggestion("models/user.py", 2)],
                ),
            ],
        })()
        text = format_backtest_report(report)
        assert "recall" in text.lower()
        assert "auth" in text
