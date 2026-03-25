"""Tests for the ingest pipeline."""

import os
import subprocess
import pytest
from dotscope.ingest import ingest, format_ingest_report


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)


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

    def test_format_report(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("")

        plan = ingest(str(tmp_path), mine_history=False, dry_run=True)
        report = format_ingest_report(plan)
        assert "Ingest Report" in report

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
