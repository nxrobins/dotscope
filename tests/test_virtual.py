"""Tests for virtual scope detection."""

import os
import pytest
from dotscope.graph import build_graph
from dotscope.virtual import detect_virtual_scopes, format_virtual_scopes


class TestVirtualScopes:
    def test_detects_hub(self, tmp_path):
        """A file imported by 3+ files from 2+ dirs should create a virtual scope."""
        # Hub: models/user.py
        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("")
        (models / "user.py").write_text("class User: pass\n")

        # Three importers from different directories
        for name in ("auth", "api", "admin"):
            d = tmp_path / name
            d.mkdir()
            (d / "__init__.py").write_text("")
            (d / "handler.py").write_text("from models.user import User\n")

        (tmp_path / ".git").mkdir()
        graph = build_graph(str(tmp_path))
        scopes = detect_virtual_scopes(graph, min_importers=3, min_directories=2)

        assert len(scopes) >= 1
        assert any("user" in s.description.lower() for s in scopes)

    def test_no_virtual_for_utility_dirs(self, tmp_path):
        """Files in utils/ shouldn't create virtual scopes (they connect everything)."""
        utils = tmp_path / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("")
        (utils / "helpers.py").write_text("def help(): pass\n")

        for name in ("a", "b", "c"):
            d = tmp_path / name
            d.mkdir()
            (d / "__init__.py").write_text("")
            (d / "main.py").write_text("from utils.helpers import help\n")

        (tmp_path / ".git").mkdir()
        graph = build_graph(str(tmp_path))
        scopes = detect_virtual_scopes(graph)
        # utils should be filtered out
        assert not any("helpers" in s.description for s in scopes)

    def test_no_virtual_when_too_few_importers(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("")
        (models / "item.py").write_text("class Item: pass\n")

        d = tmp_path / "shop"
        d.mkdir()
        (d / "__init__.py").write_text("")
        (d / "cart.py").write_text("from models.item import Item\n")

        (tmp_path / ".git").mkdir()
        graph = build_graph(str(tmp_path))
        scopes = detect_virtual_scopes(graph, min_importers=3)
        assert len(scopes) == 0

    def test_format(self, tmp_path):
        (tmp_path / ".git").mkdir()
        graph = build_graph(str(tmp_path))
        text = format_virtual_scopes([], str(tmp_path))
        assert "No cross-cutting" in text
