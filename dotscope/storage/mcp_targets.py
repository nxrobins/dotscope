"""Low-level MCP target inspection and config writer helpers."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .atomic import atomic_write_json, atomic_write_text, read_json_with_retry, read_text_with_retry
from .mcp_runtime import McpLaunchSpec

_DOTSCOPE_SERVER_NAME = "dotscope"
_CODEX_SECTION_RE = re.compile(r"(?ms)^\[mcp_servers\.dotscope\]\n.*?(?=^\[|\Z)")


@dataclass(frozen=True)
class McpTargetSpec:
    label: str
    scope: str
    kind: str
    path: str
    top_key: str | None = None
    allow_legacy_flat: bool = False


def _claude_desktop_config_path() -> str:
    """Find Claude Desktop config file."""
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        path = Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    return str(path) if path.parent.exists() else ""


def _windsurf_config_path() -> str:
    """Find Windsurf/Codeium MCP config file."""
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", ""))
    else:
        base = Path.home()
    path = base / ".codeium" / "windsurf" / "mcp_config.json"
    return str(path) if path.parent.exists() else ""


def _build_json_entry(launcher: McpLaunchSpec | None, repo_root: str) -> dict | None:
    if launcher is None:
        return None
    return {
        "command": launcher.command,
        "args": list(launcher.args) + ["--root", os.path.abspath(repo_root)],
    }


def _write_json_config(
    config_path: str,
    top_key: str,
    entry: dict,
    *,
    allow_legacy_flat: bool = False,
    repair_invalid: bool = False,
    force: bool = False,
) -> bool:
    """Add or repair dotscope in a JSON MCP config under `top_key`."""
    config = _load_json_config(config_path, repair_invalid=repair_invalid)
    if allow_legacy_flat and _looks_like_legacy_flat_server_map(config):
        config = {top_key: config}

    servers = config.setdefault(top_key, {})
    if not isinstance(servers, dict):
        if repair_invalid:
            servers = {}
            config[top_key] = servers
        else:
            raise ValueError(f"{config_path} has a non-object '{top_key}' section")

    if not force and servers.get(_DOTSCOPE_SERVER_NAME) == entry:
        return False

    servers[_DOTSCOPE_SERVER_NAME] = entry
    atomic_write_json(config_path, config)
    return True


def _write_cursor_config(
    config_path: str,
    entry: dict,
    *,
    repair_invalid: bool = False,
    force: bool = False,
) -> bool:
    """Add or repair dotscope in Cursor's current mcpServers config."""
    return _write_json_config(
        config_path,
        "mcpServers",
        entry,
        allow_legacy_flat=True,
        repair_invalid=repair_invalid,
        force=force,
    )


def _write_codex_toml(
    config_path: str,
    launcher: McpLaunchSpec,
    repo_root: str,
    *,
    force: bool = False,
) -> bool:
    """Add or repair dotscope MCP config in Codex CLI TOML."""
    existing = ""
    if os.path.exists(config_path):
        existing = read_text_with_retry(config_path)

    block = _render_codex_block(launcher, repo_root)
    match = _CODEX_SECTION_RE.search(existing)
    if match:
        current = match.group(0)
        if not force and current.strip() == block.strip():
            return False
        updated = existing[: match.start()] + block + existing[match.end() :]
    else:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        updated = prefix + block

    atomic_write_text(config_path, updated)
    return True


def _inspect_json_target(
    label: str,
    path: str,
    top_key: str,
    expected_entry: dict | None,
    *,
    allow_legacy_flat: bool = False,
) -> dict:
    if not path:
        return {"label": label, "path": path, "status": "unavailable"}
    if not os.path.exists(path):
        return {"label": label, "path": path, "status": "missing"}

    try:
        config = _load_json_config(path)
    except ValueError as exc:
        return {"label": label, "path": path, "status": "error", "error": str(exc)}

    if allow_legacy_flat and _looks_like_legacy_flat_server_map(config):
        if expected_entry is None:
            return {"label": label, "path": path, "status": "legacy-flat"}
        config = {top_key: config}

    servers = config.get(top_key)
    if not isinstance(servers, dict):
        return {"label": label, "path": path, "status": "missing"}

    actual = servers.get(_DOTSCOPE_SERVER_NAME)
    if actual is None:
        return {"label": label, "path": path, "status": "missing"}
    if expected_entry is None:
        return {"label": label, "path": path, "status": "present"}
    if actual == expected_entry:
        return {"label": label, "path": path, "status": "ok"}
    return {"label": label, "path": path, "status": "stale", "actual": actual}


def _inspect_codex_target(
    label: str,
    path: str,
    launcher: McpLaunchSpec | None,
    repo_root: str,
) -> dict:
    if not os.path.exists(path):
        return {"label": label, "path": path, "status": "missing"}

    content = read_text_with_retry(path)
    match = _CODEX_SECTION_RE.search(content)
    if not match:
        return {"label": label, "path": path, "status": "missing"}
    if launcher is None:
        return {"label": label, "path": path, "status": "present"}

    expected = _render_codex_block(launcher, repo_root).strip()
    actual = match.group(0).strip()
    if actual == expected:
        return {"label": label, "path": path, "status": "ok"}
    return {"label": label, "path": path, "status": "stale"}


def _load_json_config(config_path: str, *, repair_invalid: bool = False) -> dict:
    if not os.path.exists(config_path):
        return {}

    try:
        data = read_json_with_retry(config_path)
    except json.JSONDecodeError as exc:
        if repair_invalid:
            return {}
        raise ValueError(f"{config_path} contains invalid JSON") from exc
    except OSError as exc:
        raise ValueError(f"{config_path} could not be read: {exc}") from exc

    if not isinstance(data, dict):
        if repair_invalid:
            return {}
        raise ValueError(f"{config_path} must contain a JSON object at the top level")
    return data


def _looks_like_legacy_flat_server_map(config: dict) -> bool:
    if not config or not isinstance(config, dict):
        return False
    if "mcpServers" in config or "servers" in config:
        return False
    return all(
        isinstance(value, dict)
        and any(key in value for key in ("command", "url", "args", "env"))
        for value in config.values()
    )


def _render_codex_block(launcher: McpLaunchSpec, repo_root: str) -> str:
    args = list(launcher.args) + ["--root", os.path.abspath(repo_root)]
    return (
        "[mcp_servers.dotscope]\n"
        f"command = {json.dumps(launcher.command)}\n"
        f"args = {json.dumps(args)}\n"
    )
