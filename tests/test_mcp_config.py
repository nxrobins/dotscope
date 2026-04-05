"""Tests for MCP config generation across all supported clients."""

import json
import os
import tempfile

import pytest

from dotscope.storage.mcp_config import (
    _write_json_config,
    _write_cursor_config,
    _write_codex_toml,
    configure_mcp,
)


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary repo root."""
    return str(tmp_path)


# ---------------------------------------------------------------------------
# _write_json_config (shared by Claude Desktop, Claude Code, Windsurf, VS Code)
# ---------------------------------------------------------------------------


class TestWriteJsonConfig:
    def test_creates_new_file_with_mcpservers(self, tmp_path):
        path = str(tmp_path / "config.json")
        assert _write_json_config(path, "mcpServers", {"command": "dotscope-mcp"})

        with open(path) as f:
            data = json.load(f)
        assert data["mcpServers"]["dotscope"]["command"] == "dotscope-mcp"

    def test_creates_new_file_with_servers_key(self, tmp_path):
        """VS Code Copilot uses 'servers' not 'mcpServers'."""
        path = str(tmp_path / "mcp.json")
        assert _write_json_config(path, "servers", {"command": "dotscope-mcp"})

        with open(path) as f:
            data = json.load(f)
        assert "servers" in data
        assert "mcpServers" not in data
        assert data["servers"]["dotscope"]["command"] == "dotscope-mcp"

    def test_merges_into_existing_config(self, tmp_path):
        path = str(tmp_path / "config.json")
        existing = {"mcpServers": {"other-server": {"command": "other"}}, "someKey": 42}
        with open(path, "w") as f:
            json.dump(existing, f)

        assert _write_json_config(path, "mcpServers", {"command": "dotscope-mcp"})

        with open(path) as f:
            data = json.load(f)
        assert "other-server" in data["mcpServers"]
        assert "dotscope" in data["mcpServers"]
        assert data["someKey"] == 42

    def test_idempotent_skips_if_exists(self, tmp_path):
        path = str(tmp_path / "config.json")
        _write_json_config(path, "mcpServers", {"command": "dotscope-mcp"})
        assert not _write_json_config(path, "mcpServers", {"command": "dotscope-mcp"})

    def test_creates_parent_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "deep" / "config.json")
        assert _write_json_config(path, "mcpServers", {"command": "dotscope-mcp"})
        assert os.path.exists(path)


# ---------------------------------------------------------------------------
# Cursor (flat structure — regression test)
# ---------------------------------------------------------------------------


class TestCursorConfig:
    def test_flat_structure_no_mcpservers_wrapper(self, tmp_path):
        """Cursor uses flat JSON — server names are top-level keys."""
        path = str(tmp_path / ".cursor" / "mcp.json")
        assert _write_cursor_config(path, str(tmp_path))

        with open(path) as f:
            data = json.load(f)
        # Must NOT have mcpServers wrapper
        assert "mcpServers" not in data
        # Server name is a top-level key
        assert "dotscope" in data
        assert data["dotscope"]["command"] == "dotscope-mcp"

    def test_includes_root_arg(self, tmp_path):
        path = str(tmp_path / "mcp.json")
        _write_cursor_config(path, str(tmp_path))

        with open(path) as f:
            data = json.load(f)
        assert "--root" in data["dotscope"]["args"]

    def test_idempotent(self, tmp_path):
        path = str(tmp_path / "mcp.json")
        _write_cursor_config(path, str(tmp_path))
        assert not _write_cursor_config(path, str(tmp_path))

    def test_preserves_existing_servers(self, tmp_path):
        path = str(tmp_path / "mcp.json")
        with open(path, "w") as f:
            json.dump({"other": {"command": "other-cmd"}}, f)

        _write_cursor_config(path, str(tmp_path))

        with open(path) as f:
            data = json.load(f)
        assert "other" in data
        assert "dotscope" in data


# ---------------------------------------------------------------------------
# Codex CLI (TOML with dupe guard)
# ---------------------------------------------------------------------------


class TestCodexToml:
    def test_creates_new_toml(self, tmp_path):
        path = str(tmp_path / ".codex" / "config.toml")
        assert _write_codex_toml(path, str(tmp_path))

        with open(path) as f:
            content = f.read()
        assert "[mcp_servers.dotscope]" in content
        assert 'command = "dotscope-mcp"' in content

    def test_appends_to_existing(self, tmp_path):
        path = str(tmp_path / "config.toml")
        with open(path, "w") as f:
            f.write("[some_other_section]\nkey = \"value\"\n")

        _write_codex_toml(path, str(tmp_path))

        with open(path) as f:
            content = f.read()
        assert "[some_other_section]" in content
        assert "[mcp_servers.dotscope]" in content

    def test_dupe_guard_skips_if_exists(self, tmp_path):
        path = str(tmp_path / "config.toml")
        _write_codex_toml(path, str(tmp_path))
        assert not _write_codex_toml(path, str(tmp_path))

    def test_creates_parent_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "config.toml")
        assert _write_codex_toml(path, str(tmp_path))
        assert os.path.exists(path)
