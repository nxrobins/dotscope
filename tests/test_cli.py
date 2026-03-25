"""Tests for CLI commands."""

import os
import json
import pytest
from dotscope.cli import main


class TestCLIResolve:
    def test_resolve_plain(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["resolve", "auth", "--no-related"])
        output = capsys.readouterr().out
        assert "handler.py" in output

    def test_resolve_json(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["resolve", "auth", "--json", "--no-related"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "files" in data
        assert "context" in data
        assert data["file_count"] > 0

    def test_resolve_with_budget(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["resolve", "auth", "--json", "--budget", "100", "--no-related"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "files" in data

    def test_resolve_composition(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["resolve", "auth+payments", "--json", "--no-related"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["file_count"] > 0


class TestCLIContext:
    def test_context(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["context", "auth"])
        output = capsys.readouterr().out
        assert "JWT tokens" in output

    def test_context_section(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["context", "auth", "--section", "Invariants"])
        output = capsys.readouterr().out
        assert "deactivate" in output


class TestCLIMatch:
    def test_match(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["match", "fix the JWT token bug"])
        output = capsys.readouterr().out
        assert "auth" in output.lower()


class TestCLIValidate:
    def test_validate(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["validate"])
        output = capsys.readouterr().out
        assert "scope(s)" in output


class TestCLIStats:
    def test_stats(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["stats"])
        output = capsys.readouterr().out
        assert "Repository" in output
        assert "Files" in output or "Scope" in output


class TestCLITree:
    def test_tree(self, tmp_project, capsys):
        os.chdir(str(tmp_project))
        main(["tree"])
        output = capsys.readouterr().out
        assert "auth" in output.lower()


class TestCLIInit:
    def test_init_template(self, tmp_path, capsys):
        target = tmp_path / "newmodule"
        target.mkdir()
        main(["init", "--dir", str(target)])
        output = capsys.readouterr().out
        assert "Created" in output
        assert (target / ".scope").exists()

    def test_init_scan(self, tmp_path, capsys):
        target = tmp_path / "mylib"
        target.mkdir()
        (target / "module.py").write_text("def foo(): pass\n")

        main(["init", "--scan", "--dir", str(target)])
        output = capsys.readouterr().out
        assert "Created" in output
        assert (target / ".scope").exists()

    def test_init_refuses_overwrite(self, tmp_path):
        (tmp_path / ".scope").write_text("description: Existing\n")
        with pytest.raises(SystemExit):
            main(["init", "--dir", str(tmp_path)])
