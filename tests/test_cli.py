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
    def test_init_runs_without_crash(self, tmp_path):
        """Init should not crash on an empty directory."""
        # Create a minimal git repo so ingest has something to work with
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "module.py").write_text("def foo(): pass\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )
        # Should not raise
        try:
            main(["init", "--quiet", str(tmp_path)])
        except SystemExit:
            pass  # May exit 0 or 1 depending on ingest result
