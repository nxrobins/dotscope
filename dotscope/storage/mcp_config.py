"""Auto-detect IDE and configure MCP server.

Finds Claude Desktop, Claude Code, and Cursor configs.
Writes the dotscope MCP entry if not already present.
"""

import json
import os
import sys
from pathlib import Path


def configure_mcp(repo_root: str) -> list:
    """Detect IDEs and write MCP config. Returns list of configured IDEs."""
    configured = []

    # Claude Desktop
    path = _claude_desktop_config_path()
    if path:
        if _add_mcp_entry(path, repo_root):
            configured.append("Claude Desktop")

    # Claude Code (.claude/settings.json in project)
    cc_path = os.path.join(repo_root, ".claude", "settings.json")
    if _add_mcp_entry(cc_path, None):
        configured.append("Claude Code")

    # Cursor (.cursor/mcp.json in project)
    cursor_path = os.path.join(repo_root, ".cursor", "mcp.json")
    if _add_mcp_entry_cursor(cursor_path, repo_root):
        configured.append("Cursor")

    return configured


def _claude_desktop_config_path() -> str:
    """Find Claude Desktop config file."""
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        p = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    return str(p) if p.parent.exists() else ""


def _add_mcp_entry(config_path: str, repo_root: str) -> bool:
    """Add dotscope to an MCP config file. Returns True if written."""
    try:
        config = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

        servers = config.setdefault("mcpServers", {})
        if "dotscope" in servers:
            return False  # Already configured

        entry = {"command": "dotscope-mcp"}
        if repo_root:
            entry["args"] = ["--root", os.path.abspath(repo_root)]

        servers["dotscope"] = entry

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return True
    except (IOError, json.JSONDecodeError, OSError):
        return False


def _add_mcp_entry_cursor(config_path: str, repo_root: str) -> bool:
    """Add dotscope to Cursor's MCP config."""
    try:
        config = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

        if "dotscope" in config:
            return False

        config["dotscope"] = {
            "command": "dotscope-mcp",
            "args": ["--root", os.path.abspath(repo_root)],
        }

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return True
    except (IOError, json.JSONDecodeError, OSError):
        return False
