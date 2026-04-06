"""Tests for output formatting: plain, json, cursor."""

import json

import pytest

from dotscope.formatter import format_resolved
from dotscope.models.core import ResolvedScope


class TestFormatJson:
    def test_returns_valid_json(self):
        resolved = ResolvedScope(
            files=["/repo/auth/handler.py", "/repo/auth/tokens.py"],
            context="Auth module context",
            token_estimate=500,
            scope_chain=["/repo/auth/.scope"],
        )
        output = format_resolved(resolved, fmt="json", root="/repo")
        data = json.loads(output)

        assert "files" in data
        assert len(data["files"]) == 2
        assert data["token_estimate"] == 500
        assert data["file_count"] == 2

    def test_excluded_count_present_when_excluded(self):
        resolved = ResolvedScope(
            files=["/repo/a.py"],
            excluded_files=["/repo/b.py", "/repo/c.py"],
            scope_chain=["/repo/.scope"],
        )
        output = format_resolved(resolved, fmt="json", root="/repo")
        data = json.loads(output)
        assert data["excluded_count"] == 2

    def test_no_excluded_count_when_empty(self):
        resolved = ResolvedScope(
            files=["/repo/a.py"],
            scope_chain=["/repo/.scope"],
        )
        output = format_resolved(resolved, fmt="json", root="/repo")
        data = json.loads(output)
        assert "excluded_count" not in data


class TestFormatPlain:
    def test_returns_readable_string(self):
        resolved = ResolvedScope(
            files=["/repo/auth/handler.py"],
            context="Auth context",
            scope_chain=["/repo/auth/.scope"],
        )
        output = format_resolved(resolved, fmt="plain", root="/repo")
        assert isinstance(output, str)
        assert "handler.py" in output

    def test_truncation_note(self):
        resolved = ResolvedScope(
            files=["/repo/a.py"],
            truncated=True,
            token_estimate=8000,
            scope_chain=["/repo/.scope"],
        )
        output = format_resolved(resolved, fmt="plain", root="/repo")
        assert "Truncated" in output
        assert "8000" in output

    def test_excluded_note(self):
        resolved = ResolvedScope(
            files=["/repo/a.py"],
            excluded_files=["/repo/b.py"],
            scope_chain=["/repo/.scope"],
        )
        output = format_resolved(resolved, fmt="plain", root="/repo")
        assert "Excluded: 1" in output


class TestFormatCursor:
    def test_includes_context_header(self):
        resolved = ResolvedScope(
            files=["/repo/a.py"],
            context="Important context here",
            scope_chain=["/repo/.scope"],
        )
        output = format_resolved(resolved, fmt="cursor", root="/repo")
        assert "# Scope Context" in output
        assert "# Relevant Files" in output
