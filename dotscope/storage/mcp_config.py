"""Auto-detect IDE and configure MCP server.

Finds Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot,
Codex CLI, JetBrains, and Zed configs. Writes the dotscope MCP entry
if not already present.
"""

import json
import os
import sys
from pathlib import Path


def configure_mcp(repo_root: str) -> list:
    """Detect IDEs and write MCP config. Returns list of configured IDEs."""
    configured = []

    # --- JSON-based clients with mcpServers wrapper ---

    # Claude Desktop (global, platform-specific)
    path = _claude_desktop_config_path()
    if path:
        if _write_json_config(path, "mcpServers", _entry_with_root(repo_root)):
            configured.append("Claude Desktop")

    # Claude Code — new .mcp.json at repo root (preferred)
    mcp_json_path = os.path.join(repo_root, ".mcp.json")
    if _write_json_config(mcp_json_path, "mcpServers", {"type": "stdio", "command": "dotscope-mcp"}):
        configured.append("Claude Code (.mcp.json)")

    # Claude Code — legacy .claude/settings.json (backward compat, will be removed)
    cc_legacy_path = os.path.join(repo_root, ".claude", "settings.json")
    if _write_json_config(cc_legacy_path, "mcpServers", {"command": "dotscope-mcp"}):
        configured.append("Claude Code (legacy)")

    # Windsurf (global)
    windsurf_path = _windsurf_config_path()
    if windsurf_path:
        if _write_json_config(windsurf_path, "mcpServers", _entry_with_root(repo_root)):
            configured.append("Windsurf")

    # --- JSON-based clients with different top-level keys ---

    # VS Code Copilot (uses "servers", not "mcpServers")
    vscode_path = os.path.join(repo_root, ".vscode", "mcp.json")
    if _write_json_config(vscode_path, "servers", {"command": "dotscope-mcp"}):
        configured.append("VS Code Copilot")

    # --- Cursor (flat structure, no wrapper key) ---

    cursor_path = os.path.join(repo_root, ".cursor", "mcp.json")
    if _write_cursor_config(cursor_path, repo_root):
        configured.append("Cursor")

    # --- TOML-based clients ---

    # Codex CLI
    codex_path = os.path.join(repo_root, ".codex", "config.toml")
    if _write_codex_toml(codex_path, repo_root):
        configured.append("Codex CLI")

    # --- Instruction-only clients ---

    _print_jetbrains_instructions(repo_root)
    _print_zed_instructions(repo_root)

    return configured


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

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


def _windsurf_config_path() -> str:
    """Find Windsurf/Codeium MCP config file."""
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", ""))
    else:
        base = Path.home()
    p = base / ".codeium" / "windsurf" / "mcp_config.json"
    # Return path even if parent doesn't exist yet — we'll mkdir on write
    return str(p)


def _entry_with_root(repo_root: str) -> dict:
    """Build a standard MCP entry with --root arg."""
    return {
        "command": "dotscope-mcp",
        "args": ["--root", os.path.abspath(repo_root)],
    }


# ---------------------------------------------------------------------------
# JSON config writer (shared by Claude Desktop, Claude Code, Windsurf, VS Code)
# ---------------------------------------------------------------------------

def _write_json_config(config_path: str, top_key: str, entry: dict) -> bool:
    """Add dotscope to a JSON MCP config under `top_key`. Returns True if written."""
    try:
        config = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

        servers = config.setdefault(top_key, {})
        if "dotscope" in servers:
            return False  # Already configured

        servers["dotscope"] = entry

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except (IOError, json.JSONDecodeError, OSError):
        return False


# ---------------------------------------------------------------------------
# Cursor (flat structure — no mcpServers wrapper)
# ---------------------------------------------------------------------------

def _write_cursor_config(config_path: str, repo_root: str) -> bool:
    """Add dotscope to Cursor's MCP config (flat JSON, no wrapper key)."""
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


# ---------------------------------------------------------------------------
# Codex CLI (TOML string template with dupe guard)
# ---------------------------------------------------------------------------

def _write_codex_toml(config_path: str, repo_root: str) -> bool:
    """Append dotscope MCP config to Codex CLI's TOML file."""
    try:
        existing = ""
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                existing = f.read()

        if "[mcp_servers.dotscope]" in existing:
            return False  # Already configured

        block = (
            "\n[mcp_servers.dotscope]\n"
            'command = "dotscope-mcp"\n'
        )

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "a", encoding="utf-8") as f:
            f.write(block)
        return True
    except (IOError, OSError):
        return False


# ---------------------------------------------------------------------------
# Instruction-only clients (JetBrains, Zed)
# ---------------------------------------------------------------------------

def _print_jetbrains_instructions(repo_root: str) -> None:
    """Print manual MCP setup instructions for JetBrains IDEs."""
    root = os.path.abspath(repo_root)
    print(
        f"dotscope: JetBrains \u2014 add MCP server manually:\n"
        f"  Settings > Tools > AI Assistant > MCP\n"
        f"  Command: dotscope-mcp\n"
        f"  Arguments: --root {root}",
        file=sys.stderr,
    )


def _print_zed_instructions(repo_root: str) -> None:
    """Print manual MCP setup instructions for Zed."""
    root = os.path.abspath(repo_root)
    print(
        f'dotscope: Zed \u2014 add to ~/.config/zed/settings.json:\n'
        f'  "context_servers": {{\n'
        f'    "dotscope": {{\n'
        f'      "source": "custom",\n'
        f'      "command": "dotscope-mcp",\n'
        f'      "args": ["--root", "{root}"]\n'
        f'    }}\n'
        f'  }}',
        file=sys.stderr,
    )
