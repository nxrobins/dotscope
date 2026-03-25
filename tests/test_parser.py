"""Tests for the .scope file parser."""

import os
import pytest
from dotscope.parser import parse_scope_file, parse_scopes_index, serialize_scope


class TestParseScope:
    def test_full_scope_file(self, tmp_path, scope_text):
        scope_file = tmp_path / ".scope"
        scope_file.write_text(scope_text)

        config = parse_scope_file(str(scope_file))

        assert config.description == "Authentication and session management"
        assert config.includes == ["auth/", "models/user.py", "config/auth_settings.py"]
        assert config.excludes == ["auth/tests/fixtures/", "*.generated.py"]
        assert "JWT tokens" in config.context_str
        assert "Redis" in config.context_str
        assert config.related == ["payments/.scope", "api/.scope"]
        assert config.owners == ["@alice", "@bob"]
        assert config.tags == ["security", "session-management"]
        assert config.tokens_estimate == 1247

    def test_minimal_scope(self, tmp_path):
        (tmp_path / ".scope").write_text("description: Minimal scope\n")
        config = parse_scope_file(str(tmp_path / ".scope"))

        assert config.description == "Minimal scope"
        assert config.includes == []
        assert config.excludes == []
        assert config.context is None
        assert config.related == []

    def test_missing_description_raises(self, tmp_path):
        (tmp_path / ".scope").write_text("includes:\n  - foo/\n")
        with pytest.raises(ValueError, match="Missing required 'description'"):
            parse_scope_file(str(tmp_path / ".scope"))

    def test_block_scalar_context(self, tmp_path):
        (tmp_path / ".scope").write_text(
            "description: Test\n"
            "context: |\n"
            "  Line one.\n"
            "  Line two.\n"
            "  Line three.\n"
        )
        config = parse_scope_file(str(tmp_path / ".scope"))
        assert "Line one." in config.context_str
        assert "Line two." in config.context_str
        assert "Line three." in config.context_str

    def test_comments_stripped(self, tmp_path):
        (tmp_path / ".scope").write_text(
            "# Top comment\n"
            "description: Test scope  # inline comment\n"
            "includes:\n"
            "  - src/  # source directory\n"
        )
        config = parse_scope_file(str(tmp_path / ".scope"))
        assert config.description == "Test scope"
        assert config.includes == ["src/"]

    def test_related_with_inline_comments(self, tmp_path):
        (tmp_path / ".scope").write_text(
            "description: Test\n"
            "related:\n"
            "  - payments/.scope  # shares user model\n"
            "  - api/.scope       # auth middleware\n"
        )
        config = parse_scope_file(str(tmp_path / ".scope"))
        assert config.related == ["payments/.scope", "api/.scope"]


class TestParseScopesIndex:
    def test_full_index(self, tmp_path):
        (tmp_path / ".scopes").write_text(
            "version: 1\n"
            "\n"
            "scopes:\n"
            "  auth:\n"
            "    path: auth/.scope\n"
            "    keywords: [authentication, login, JWT]\n"
            "  payments:\n"
            "    path: payments/.scope\n"
            "    keywords: [billing, stripe, invoice]\n"
            "\n"
            "defaults:\n"
            "  max_tokens: 8000\n"
            "  include_related: false\n"
        )

        index = parse_scopes_index(str(tmp_path / ".scopes"))

        assert index.version == 1
        assert "auth" in index.scopes
        assert index.scopes["auth"].path == "auth/.scope"
        assert "JWT" in index.scopes["auth"].keywords
        assert "payments" in index.scopes
        assert index.max_tokens == 8000
        assert index.include_related is False


class TestSerialize:
    def test_roundtrip(self, tmp_path, scope_text):
        scope_file = tmp_path / ".scope"
        scope_file.write_text(scope_text)

        config = parse_scope_file(str(scope_file))
        serialized = serialize_scope(config)

        # Write and re-parse
        scope_file2 = tmp_path / ".scope2"
        scope_file2.write_text(serialized)
        config2 = parse_scope_file(str(scope_file2))

        assert config2.description == config.description
        assert config2.includes == config.includes
        assert set(config2.tags) == set(config.tags)
