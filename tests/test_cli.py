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

    def test_validate_emits_decode_summary_to_stderr(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        mod = tmp_path / "auth"
        mod.mkdir()
        (mod / "handler.py").write_text("def login(): pass\n")
        (mod / ".scope").write_bytes(
            b"description: Caf\xe9 scope\n"
            b"includes:\n"
            b"  - auth/\n"
        )

        os.chdir(str(tmp_path))
        main(["validate"])
        captured = capsys.readouterr()

        assert "decoded 1 repo file with replacement" in captured.err


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
    def test_init_runs_without_crash(self, tmp_path, monkeypatch):
        """Init should not crash on an empty directory."""
        # Create a minimal git repo so ingest has something to work with
        import subprocess
        monkeypatch.setattr("dotscope.storage.mcp_config.configure_mcp", lambda _root: [])
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


class TestCLIDoctor:
    def test_doctor_mcp_json(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            "dotscope.storage.mcp_config.diagnose_mcp",
            lambda _root: {
                "repo_root": str(tmp_path),
                "launcher": {
                    "ok": True,
                    "command": "/abs/path/dotscope-mcp",
                    "args": [],
                    "source": "path-script",
                },
                "managed_runtime": {
                    "status": "ok",
                    "runtime_root": str(tmp_path / "runtime"),
                    "launcher_path": "/abs/path/dotscope-mcp",
                    "package_source": "local-source",
                },
                "candidates": [{"ok": True, "command": "/abs/path/dotscope-mcp", "args": [], "source": "path-script"}],
                "targets": [{"label": "Claude Code (.mcp.json)", "path": str(tmp_path / ".mcp.json"), "status": "ok"}],
                "notes": ["note"],
            },
        )

        main(["doctor", "mcp", str(tmp_path), "--json"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["launcher"]["ok"] is True
        assert data["targets"][0]["status"] == "ok"

    def test_doctor_mcp_exits_nonzero_when_launcher_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dotscope.storage.mcp_config.diagnose_mcp",
            lambda _root: {
                "repo_root": str(tmp_path),
                "launcher": {"ok": False, "command": None, "args": [], "source": None},
                "managed_runtime": {"status": "missing", "runtime_root": str(tmp_path / "runtime")},
                "candidates": [],
                "targets": [],
                "notes": [],
            },
        )

        with pytest.raises(SystemExit) as exc:
            main(["doctor", "mcp", str(tmp_path)])
        assert exc.value.code == 1
