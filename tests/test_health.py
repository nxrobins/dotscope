"""Tests for scope health monitoring."""

import os
import time
import pytest
from dotscope.health import full_health_report, check_staleness, check_broken_paths
from dotscope.parser import parse_scope_file


class TestHealth:
    def test_healthy_project(self, tmp_project):
        report = full_health_report(str(tmp_project))
        assert report.scopes_checked == 2
        # Should have no errors for broken paths (our fixture is well-formed)
        broken = [i for i in report.issues if i.category == "broken_path" and i.severity == "error"]
        assert len(broken) == 0

    def test_broken_include_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        mod = tmp_path / "broken"
        mod.mkdir()
        (mod / ".scope").write_text(
            "description: Broken scope\n"
            "includes:\n"
            "  - nonexistent/\n"
        )

        report = full_health_report(str(tmp_path))
        errors = [i for i in report.issues if i.category == "broken_path"]
        assert len(errors) >= 1
        assert "nonexistent" in errors[0].message

    def test_staleness_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        mod = tmp_path / "stale"
        mod.mkdir()
        (mod / "code.py").write_text("# old\n")
        (mod / ".scope").write_text(
            "description: Stale scope\n"
            "includes:\n"
            "  - stale/\n"
        )

        # Make the scope file older than the code
        scope_path = str(mod / ".scope")
        old_time = time.time() - 1000
        os.utime(scope_path, (old_time, old_time))

        config = parse_scope_file(scope_path)
        issues = check_staleness(config, str(tmp_path))
        assert len(issues) >= 1
        assert issues[0].category == "staleness"

    def test_coverage_gap_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()

        # Module with scope
        scoped = tmp_path / "scoped"
        scoped.mkdir()
        (scoped / "main.py").write_text("")
        (scoped / ".scope").write_text("description: Scoped\nincludes:\n  - scoped/\n")

        # Module without scope
        unscoped = tmp_path / "unscoped"
        unscoped.mkdir()
        (unscoped / "main.py").write_text("")

        report = full_health_report(str(tmp_path))
        coverage_issues = [i for i in report.issues if i.category == "coverage"]
        assert any("unscoped" in i.message for i in coverage_issues)

    def test_scoped_dirs_counted(self, tmp_project):
        report = full_health_report(str(tmp_project))
        assert report.directories_covered >= 2  # auth + payments have scopes
