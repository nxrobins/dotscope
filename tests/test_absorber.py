"""Tests for the documentation absorber."""

import os
import pytest
from dotscope.absorber import absorb_docs


class TestAbsorber:
    def test_absorbs_readme(self, tmp_path):
        (tmp_path / "mymod").mkdir()
        (tmp_path / "mymod" / "main.py").write_text("")
        (tmp_path / "README.md").write_text("# Project\nSome info about mymod.\n")

        result = absorb_docs(str(tmp_path))
        assert "README.md" in result.doc_files_found

    def test_absorbs_module_readme(self, tmp_path):
        mod = tmp_path / "auth"
        mod.mkdir()
        (mod / "handler.py").write_text("")
        (mod / "README.md").write_text("Auth module docs.\n")

        result = absorb_docs(str(tmp_path))
        frags = result.for_module("auth")
        assert any("Auth module" in f.content for f in frags)

    def test_absorbs_signal_comments(self, tmp_path):
        mod = tmp_path / "core"
        mod.mkdir()
        (mod / "engine.py").write_text(
            "# WARNING: Do not call this without a lock\n"
            "def dangerous():\n"
            "    pass\n"
            "\n"
            "# NOTE: This uses a custom allocator\n"
            "def allocate():\n"
            "    pass\n"
        )

        result = absorb_docs(str(tmp_path))
        frags = result.for_module("core")
        warnings = [f for f in frags if f.priority >= 10]
        assert len(warnings) >= 1
        assert any("lock" in f.content for f in warnings)

    def test_absorbs_docstrings(self, tmp_path):
        mod = tmp_path / "utils"
        mod.mkdir()
        (mod / "helpers.py").write_text(
            '"""Utility helpers for data transformation."""\n\n'
            'def transform(data):\n    pass\n'
        )

        result = absorb_docs(str(tmp_path))
        frags = result.for_module("utils")
        docstrings = [f for f in frags if f.kind == "docstring"]
        assert len(docstrings) >= 1

    def test_synthesize_context_clean(self, tmp_path):
        mod = tmp_path / "api"
        mod.mkdir()
        (mod / "routes.py").write_text(
            "# WARNING: All endpoints require auth middleware\n"
            "# NOTE: Rate limiting is applied globally\n"
        )
        (mod / "README.md").write_text("API routing layer.\n")

        result = absorb_docs(str(tmp_path))
        ctx = result.synthesize_context("api")
        # Should not have [filepath] prefixes
        assert "[api/" not in ctx
        assert len(ctx) > 0

    def test_empty_project(self, tmp_path):
        result = absorb_docs(str(tmp_path))
        assert len(result.fragments) == 0

    def test_signal_regex_not_greedy(self, tmp_path):
        mod = tmp_path / "lib"
        mod.mkdir()
        (mod / "core.py").write_text(
            "# INVARIANT: amounts must be in cents  # see billing docs\n"
        )

        result = absorb_docs(str(tmp_path))
        frags = result.for_module("lib")
        invariants = [f for f in frags if "INVARIANT" in f.content]
        assert len(invariants) >= 1
        # Should capture the message but not the trailing comment
        assert "amounts must be in cents" in invariants[0].content
        assert "see billing docs" not in invariants[0].content
