"""Tests for dependency graph analysis."""

import os
import pytest
from dotscope.graph import build_graph, format_graph_summary


class TestBuildGraph:
    def test_detects_python_imports(self, tmp_path):
        mod = tmp_path / "app"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "main.py").write_text("from app.utils import helper\n")
        (mod / "utils.py").write_text("def helper(): pass\n")

        graph = build_graph(str(tmp_path))
        assert len(graph.files) >= 2
        node = graph.files.get("app/main.py")
        assert node is not None
        assert "app/utils.py" in node.imports

    def test_detects_modules(self, tmp_path):
        for name in ("auth", "api"):
            d = tmp_path / name
            d.mkdir()
            (d / "__init__.py").write_text("")
            (d / "core.py").write_text(f"# {name} core\n")

        graph = build_graph(str(tmp_path))
        assert len(graph.modules) == 2
        names = {m.directory for m in graph.modules}
        assert "auth" in names
        assert "api" in names

    def test_cohesion_calculation(self, tmp_path):
        mod = tmp_path / "tight"
        mod.mkdir()
        (mod / "__init__.py").write_text("")
        (mod / "a.py").write_text("from tight.b import foo\n")
        (mod / "b.py").write_text("def foo(): pass\n")

        graph = build_graph(str(tmp_path))
        tight_mod = next((m for m in graph.modules if m.directory == "tight"), None)
        assert tight_mod is not None
        assert tight_mod.cohesion >= 0.5  # Internal edges exist

    def test_cross_module_deps(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "__init__.py").write_text("")
        (auth / "handler.py").write_text("from models.user import User\n")

        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("")
        (models / "user.py").write_text("class User: pass\n")

        graph = build_graph(str(tmp_path))
        auth_mod = next((m for m in graph.modules if m.directory == "auth"), None)
        assert auth_mod is not None
        assert "models" in auth_mod.external_deps

    def test_format_summary(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')\n")

        graph = build_graph(str(tmp_path))
        summary = format_graph_summary(graph)
        assert "Dependency Graph" in summary

    def test_skips_hidden_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config.py").write_text("")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("")

        graph = build_graph(str(tmp_path))
        assert not any(".git" in f for f in graph.files)
