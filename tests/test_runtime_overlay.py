"""Tests for the runtime overlay system: path normalization and scope naming."""

import os

import pytest

from dotscope.runtime_overlay import logical_scope_path, scope_name_from_logical_path


class TestLogicalScopePath:
    def test_directory_name_to_scope_path(self):
        result = logical_scope_path("auth")
        assert result == "auth/.scope"

    def test_already_ends_with_scope(self):
        result = logical_scope_path("auth/.scope")
        assert result == "auth/.scope"

    def test_nested_path(self):
        result = logical_scope_path("services/auth")
        assert result == "services/auth/.scope"

    def test_trailing_slash_stripped(self):
        result = logical_scope_path("auth/")
        assert result == "auth/.scope"

    def test_absolute_path_with_root(self, tmp_path):
        abs_path = os.path.join(str(tmp_path), "auth")
        result = logical_scope_path(abs_path, root=str(tmp_path))
        assert result == "auth/.scope"

    def test_empty_string_returns_root_scope(self):
        result = logical_scope_path("")
        assert result == ".scope"


class TestScopeNameFromLogicalPath:
    def test_extracts_directory_name(self):
        result = scope_name_from_logical_path("auth/.scope")
        assert result == "auth"

    def test_nested_directory(self):
        result = scope_name_from_logical_path("services/auth")
        assert result == "services/auth"

    def test_bare_name(self):
        result = scope_name_from_logical_path("payments")
        assert result == "payments"

    def test_root_scope(self):
        result = scope_name_from_logical_path("")
        assert result == "."
