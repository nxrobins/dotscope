"""Tests for scope synchronization behavior."""

from dotscope.workflows.sync import sync_scopes


def _write_scope(path, include):
    path.write_text(
        "description: Test scope\n"
        "includes:\n"
        f"  - {include}\n"
    )


class TestSyncScopes:
    def test_repo_sync_skips_nested_non_graph_scopes_cleanly(self, tmp_path, capsys):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("def run():\n    return True\n")
        _write_scope(pkg / ".scope", "pkg/\n")

        nested = pkg / "cli"
        nested.mkdir()
        (nested / "__init__.py").write_text("")
        (nested / "main.py").write_text("from pkg.core import run\n")
        _write_scope(nested / ".scope", "pkg/cli/\n")

        count = sync_scopes(str(tmp_path))
        captured = capsys.readouterr()

        assert count == 0
        assert "Could not locate graph cluster" not in captured.err
        assert "Skipping 1 non-graph-backed scope(s): pkg/cli" in captured.err

    def test_selected_nested_scope_is_skipped_without_warning_storm(self, tmp_path, capsys):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("def run():\n    return True\n")
        _write_scope(pkg / ".scope", "pkg/\n")

        nested = pkg / "cli"
        nested.mkdir()
        (nested / "__init__.py").write_text("")
        (nested / "main.py").write_text("from pkg.core import run\n")
        _write_scope(nested / ".scope", "pkg/cli/\n")

        count = sync_scopes(str(tmp_path), scopes=["cli"])
        captured = capsys.readouterr()

        assert count == 0
        assert "Could not locate graph cluster" not in captured.err
        assert "Skipping 1 non-graph-backed scope(s): pkg/cli" in captured.err
