"""Tests for line_filter: comment and string stripping."""

from dotscope.passes.sentinel.line_filter import (
    strip_comments_and_strings,
    filter_code_lines,
)


class TestStripCommentsAndStrings:
    def test_full_line_comment(self):
        assert strip_comments_and_strings("# x.delete()") == ""

    def test_indented_comment(self):
        assert strip_comments_and_strings("    # x.delete()") == ""

    def test_inline_comment(self):
        result = strip_comments_and_strings("x.delete()  # remove it")
        assert ".delete()" in result
        assert "remove it" not in result

    def test_string_literal_content_stripped(self):
        result = strip_comments_and_strings('msg = "call .delete()"')
        assert ".delete()" not in result
        assert "msg" in result

    def test_single_quote_string(self):
        result = strip_comments_and_strings("msg = 'call .delete()'")
        assert ".delete()" not in result

    def test_code_preserved(self):
        result = strip_comments_and_strings("user.delete()")
        assert ".delete()" in result

    def test_empty_line(self):
        assert strip_comments_and_strings("") == ""

    def test_import_statement(self):
        result = strip_comments_and_strings("from models import User")
        assert "from models import User" in result

    def test_import_in_comment(self):
        result = strip_comments_and_strings("# from models import User")
        assert result == ""

    def test_import_in_string(self):
        result = strip_comments_and_strings('"from models import User"')
        assert "models" not in result


class TestFilterCodeLines:
    def test_filters_comments(self):
        lines = ["x.delete()", "# x.delete()", "y.save()"]
        result = filter_code_lines(lines)
        assert len(result) == 2
        assert any(".delete()" in r for r in result)
        assert any(".save()" in r for r in result)

    def test_empty_after_filter(self):
        lines = ["# just a comment", '  # another one']
        result = filter_code_lines(lines)
        assert result == []

    def test_string_content_removed(self):
        lines = ['error_msg = "never call .delete()"']
        result = filter_code_lines(lines)
        assert len(result) == 1
        assert ".delete()" not in result[0]
