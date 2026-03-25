"""Tests for token budgeting."""

import os
import pytest
from dotscope.budget import apply_budget
from dotscope.models import ResolvedScope


class TestBudget:
    def test_no_truncation_when_under_budget(self):
        resolved = ResolvedScope(
            files=[],
            context="Short context",
            token_estimate=10,
            scope_chain=["test"],
        )
        result = apply_budget(resolved, max_tokens=10000)
        assert not result.truncated

    def test_truncation_when_over_budget(self, tmp_path):
        # Create some files
        files = []
        for i in range(10):
            f = tmp_path / f"file{i}.py"
            f.write_text("x" * 1000)  # ~250 tokens each
            files.append(str(f))

        resolved = ResolvedScope(
            files=files,
            context="Context",
            token_estimate=2500,
            scope_chain=["test"],
        )

        result = apply_budget(resolved, max_tokens=500)
        assert result.truncated
        assert len(result.files) < len(files)

    def test_context_always_included(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("x" * 4000)

        resolved = ResolvedScope(
            files=[str(f)],
            context="Important context",
            token_estimate=1000,
            scope_chain=["test"],
        )

        result = apply_budget(resolved, max_tokens=100)
        assert "Important context" in result.context

    def test_zero_budget(self):
        resolved = ResolvedScope(
            files=["/some/file.py"],
            context="Context",
            token_estimate=100,
            scope_chain=["test"],
        )
        result = apply_budget(resolved, max_tokens=0)
        assert result.truncated
        assert len(result.files) == 0
