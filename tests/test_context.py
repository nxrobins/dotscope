"""Tests for structured context."""

from dotscope.context import parse_context, query_context


class TestStructuredContext:
    def test_plain_context(self):
        ctx = parse_context("Just a plain context string with no sections.")
        assert ctx.raw == "Just a plain context string with no sections."
        assert ctx.sections == {}

    def test_sectioned_context(self):
        ctx = parse_context(
            "Preamble text.\n"
            "\n"
            "## Invariants\n"
            "Never delete users directly.\n"
            "\n"
            "## Gotchas\n"
            "OAuth config is fragile.\n"
        )
        assert "Invariants" in ctx.sections
        assert "Gotchas" in ctx.sections
        assert "Never delete" in ctx.sections["Invariants"]
        assert "OAuth" in ctx.sections["Gotchas"]
        assert "Preamble" in ctx.sections.get("_preamble", "")

    def test_query_full(self):
        ctx = parse_context("## Invariants\nDon't do X.\n## Gotchas\nWatch out for Y.")
        result = query_context(ctx)
        assert "Invariants" in result
        assert "Gotchas" in result

    def test_query_section(self):
        ctx = parse_context("## Invariants\nDon't do X.\n## Gotchas\nWatch out for Y.")
        result = query_context(ctx, "gotchas")
        assert "Watch out for Y" in result
        assert "Don't do X" not in result

    def test_query_missing_section(self):
        ctx = parse_context("## Invariants\nSome text.")
        result = query_context(ctx, "nonexistent")
        assert result == ""

    def test_query_none_context(self):
        assert query_context(None) == ""
        assert query_context(None, "foo") == ""

    def test_empty_context(self):
        ctx = parse_context("")
        assert ctx.raw == ""
        assert ctx.sections == {}
