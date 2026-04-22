"""Auto-detect IDEs and configure a reliable dotscope MCP launcher."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path

from .atomic import atomic_write_json, atomic_write_text
from .mcp_runtime import (
    McpLaunchSpec,
    diagnose_managed_mcp_runtime,
    ensure_managed_mcp_runtime,
)

_DOTSCOPE_SERVER_NAME = "dotscope"
_MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0
_CODEX_SECTION_RE = re.compile(
    r"(?ms)^\[mcp_servers\.dotscope\]\n.*?(?=^\[|\Z)"
)


def configure_mcp(repo_root: str) -> list[str]:
    """Detect IDEs and repair/write dotscope MCP config entries."""
    repo_root = os.path.abspath(repo_root)
    try:
        launcher, _managed = ensure_managed_mcp_runtime(
            repo_root,
            probe_func=probe_mcp_launch,
        )
    except RuntimeError as exc:
        _launcher, diagnostics = collect_mcp_launch_diagnostics(repo_root)
        message = f"{exc}\n{_format_launch_failure(diagnostics)}"
        raise RuntimeError(message) from exc

    entry = _build_json_entry(launcher, repo_root)
    configured: list[str] = []

    path = _claude_desktop_config_path()
    if path:
        _attempt_config_write(
            configured,
            "Claude Desktop",
            lambda: _write_json_config(path, "mcpServers", entry),
        )

    mcp_json_path = os.path.join(repo_root, ".mcp.json")
    _attempt_config_write(
        configured,
        "Claude Code (.mcp.json)",
        lambda: _write_json_config(mcp_json_path, "mcpServers", entry),
    )

    cc_legacy_path = os.path.join(repo_root, ".claude", "settings.json")
    _attempt_config_write(
        configured,
        "Claude Code (legacy)",
        lambda: _write_json_config(cc_legacy_path, "mcpServers", entry),
    )

    windsurf_path = _windsurf_config_path()
    if windsurf_path:
        _attempt_config_write(
            configured,
            "Windsurf",
            lambda: _write_json_config(windsurf_path, "mcpServers", entry),
        )

    vscode_path = os.path.join(repo_root, ".vscode", "mcp.json")
    _attempt_config_write(
        configured,
        "VS Code Copilot",
        lambda: _write_json_config(vscode_path, "servers", entry),
    )

    cursor_path = os.path.join(repo_root, ".cursor", "mcp.json")
    _attempt_config_write(
        configured,
        "Cursor",
        lambda: _write_cursor_config(cursor_path, entry),
    )

    codex_path = os.path.join(repo_root, ".codex", "config.toml")
    _attempt_config_write(
        configured,
        "Codex CLI",
        lambda: _write_codex_toml(codex_path, launcher, repo_root),
    )

    _print_jetbrains_instructions(repo_root, launcher)
    _print_zed_instructions(repo_root, launcher)

    return configured


def diagnose_mcp(repo_root: str) -> dict:
    """Inspect MCP launcher health and expected client config state."""
    repo_root = os.path.abspath(repo_root)
    managed = diagnose_managed_mcp_runtime(repo_root, probe_func=probe_mcp_launch)
    launcher = None
    if managed["status"] == "ok":
        launcher = McpLaunchSpec(
            command=managed["launcher_path"],
            args=(),
            source="managed-runtime",
        )
    entry = _build_json_entry(launcher, repo_root) if launcher else None
    _ambient_launcher, candidates = collect_mcp_launch_diagnostics(repo_root)

    targets = []
    path = _claude_desktop_config_path()
    if path:
        targets.append(_inspect_json_target("Claude Desktop", path, "mcpServers", entry))
    targets.extend(
        [
            _inspect_json_target(
                "Claude Code (.mcp.json)",
                os.path.join(repo_root, ".mcp.json"),
                "mcpServers",
                entry,
            ),
            _inspect_json_target(
                "Claude Code (legacy)",
                os.path.join(repo_root, ".claude", "settings.json"),
                "mcpServers",
                entry,
            ),
            _inspect_json_target(
                "Windsurf",
                _windsurf_config_path(),
                "mcpServers",
                entry,
            ),
            _inspect_json_target(
                "VS Code Copilot",
                os.path.join(repo_root, ".vscode", "mcp.json"),
                "servers",
                entry,
            ),
            _inspect_json_target(
                "Cursor",
                os.path.join(repo_root, ".cursor", "mcp.json"),
                "mcpServers",
                entry,
                allow_legacy_flat=True,
            ),
            _inspect_codex_target(
                "Codex CLI",
                os.path.join(repo_root, ".codex", "config.toml"),
                launcher,
                repo_root,
            ),
        ]
    )

    return {
        "repo_root": repo_root,
        "launcher": {
            "ok": launcher is not None,
            "command": launcher.command if launcher else None,
            "args": list(launcher.args) if launcher else [],
            "source": launcher.source if launcher else None,
        },
        "managed_runtime": managed,
        "candidates": candidates,
        "targets": targets,
        "notes": [
            "Some clients still require an explicit trust or approval prompt before they start a configured server.",
            "Use `dotscope init` to install or repair the managed MCP runtime and rewrite configs to point at it.",
        ],
    }


def collect_mcp_launch_diagnostics(repo_root: str) -> tuple[McpLaunchSpec | None, list[dict]]:
    """Return the first working launcher plus probe details for all candidates."""
    repo_root = os.path.abspath(repo_root)
    selected: McpLaunchSpec | None = None
    diagnostics: list[dict] = []

    for candidate in _iter_launch_candidates():
        probe = probe_mcp_launch(candidate, repo_root)
        diagnostics.append(
            {
                "command": candidate.command,
                "args": list(candidate.args),
                "source": candidate.source,
                **probe,
            }
        )
        if probe.get("ok") and selected is None:
            selected = candidate

    return selected, diagnostics


def probe_mcp_launch(
    launcher: McpLaunchSpec,
    repo_root: str,
    timeout_seconds: float = _DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> dict:
    """Exercise a launcher with a real initialize/tools-list handshake."""
    failures = []
    for protocol_version in _MCP_PROTOCOL_VERSIONS:
        result = _probe_with_protocol(
            launcher,
            repo_root,
            protocol_version=protocol_version,
            timeout_seconds=timeout_seconds,
        )
        if result.get("ok"):
            return result
        failures.append(result)

    last = failures[-1] if failures else {"error": "No protocol versions attempted"}
    return {
        "ok": False,
        "error": last.get("error", "No working MCP response"),
        "stderr": last.get("stderr", ""),
        "attempts": failures,
    }


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
    return str(base / ".codeium" / "windsurf" / "mcp_config.json")


def _build_json_entry(launcher: McpLaunchSpec | None, repo_root: str) -> dict | None:
    if launcher is None:
        return None
    return {
        "command": launcher.command,
        "args": list(launcher.args) + ["--root", os.path.abspath(repo_root)],
    }


def _attempt_config_write(configured: list[str], label: str, writer) -> None:
    try:
        if writer():
            configured.append(label)
    except Exception as exc:
        print(f"dotscope: failed to configure {label}: {exc}", file=sys.stderr)


def _write_json_config(
    config_path: str,
    top_key: str,
    entry: dict,
    *,
    allow_legacy_flat: bool = False,
) -> bool:
    """Add or repair dotscope in a JSON MCP config under `top_key`."""
    config = _load_json_config(config_path)
    if allow_legacy_flat and _looks_like_legacy_flat_server_map(config):
        config = {top_key: config}

    servers = config.setdefault(top_key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{config_path} has a non-object '{top_key}' section")

    if servers.get(_DOTSCOPE_SERVER_NAME) == entry:
        return False

    servers[_DOTSCOPE_SERVER_NAME] = entry
    atomic_write_json(config_path, config)
    return True


def _write_cursor_config(config_path: str, entry: dict) -> bool:
    """Add or repair dotscope in Cursor's current mcpServers config."""
    return _write_json_config(config_path, "mcpServers", entry, allow_legacy_flat=True)


def _write_codex_toml(config_path: str, launcher: McpLaunchSpec, repo_root: str) -> bool:
    """Add or repair dotscope MCP config in Codex CLI TOML."""
    existing = ""
    if os.path.exists(config_path):
        existing = Path(config_path).read_text(encoding="utf-8")

    block = _render_codex_block(launcher, repo_root)
    match = _CODEX_SECTION_RE.search(existing)
    if match:
        current = match.group(0)
        if current.strip() == block.strip():
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

    content = Path(path).read_text(encoding="utf-8")
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


def _load_json_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path} contains invalid JSON") from exc

    if not isinstance(data, dict):
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


def _iter_launch_candidates() -> list[McpLaunchSpec]:
    exe_name = "dotscope-mcp.exe" if os.name == "nt" else "dotscope-mcp"
    candidates: list[McpLaunchSpec] = []

    if sys.executable:
        candidates.append(
            McpLaunchSpec(
                command=os.path.abspath(sys.executable),
                args=("-m", "dotscope.mcp"),
                source="current-python",
            )
        )

    scripts_dir = sysconfig.get_path("scripts")
    if scripts_dir:
        script_path = Path(scripts_dir) / exe_name
        if script_path.exists():
            candidates.append(
                McpLaunchSpec(
                    command=str(script_path.resolve()),
                    args=(),
                    source="current-env-script",
                )
            )

    for path_script in _iter_path_scripts("dotscope-mcp"):
        candidates.append(
            McpLaunchSpec(
                command=os.path.abspath(path_script),
                args=(),
                source="path-script",
            )
        )

    unique: list[McpLaunchSpec] = []
    seen = set()
    for candidate in candidates:
        key = (candidate.command, candidate.args)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _iter_path_scripts(command_name: str) -> list[str]:
    matches: list[str] = []
    if os.name == "nt":
        suffixes = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
    else:
        suffixes = [""]

    for raw_dir in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_dir:
            continue
        base = Path(raw_dir)
        for suffix in suffixes:
            candidate = base / f"{command_name}{suffix}"
            if candidate.exists():
                matches.append(str(candidate))
    return matches


def _probe_with_protocol(
    launcher: McpLaunchSpec,
    repo_root: str,
    *,
    protocol_version: str,
    timeout_seconds: float,
) -> dict:
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            launcher.argv(repo_root),
            cwd=os.path.abspath(repo_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_probe_env(repo_root),
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc), "stderr": "", "protocol_version": protocol_version}

    try:
        _write_mcp_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "dotscope-doctor", "version": "1"},
                },
            },
        )
        init_response = _read_mcp_response(proc, expected_id=1, timeout_seconds=timeout_seconds)
        if init_response is None:
            return {
                "ok": False,
                "error": _early_exit_error(proc, "initialize"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
            }
        if "error" in init_response:
            return {
                "ok": False,
                "error": init_response["error"].get("message", "initialize failed"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
            }

        _write_mcp_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        _write_mcp_message(
            proc.stdin,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_response = _read_mcp_response(proc, expected_id=2, timeout_seconds=timeout_seconds)
        if tools_response is None:
            return {
                "ok": False,
                "error": _early_exit_error(proc, "tools/list"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
            }
        if "error" in tools_response:
            return {
                "ok": False,
                "error": tools_response["error"].get("message", "tools/list failed"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
            }

        tools = tools_response.get("result", {}).get("tools", [])
        names = [tool.get("name") for tool in tools if isinstance(tool, dict) and tool.get("name")]
        scope_probe = _probe_scope_resolution(proc, timeout_seconds=timeout_seconds)
        if not scope_probe.get("ok"):
            return {
                "ok": False,
                "error": scope_probe.get("error", "scope probe failed"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
                "tool_count": len(names),
                "tools": names[:8],
            }
        return {
            "ok": True,
            "protocol_version": protocol_version,
            "tool_count": len(names),
            "tools": names[:8],
            "scope_probe": scope_probe,
            "stderr": _safe_stderr(proc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "stderr": _safe_stderr(proc),
            "protocol_version": protocol_version,
        }
    finally:
        _terminate_process(proc)


def _write_mcp_message(stream, payload: dict) -> None:
    if stream is None:
        raise ValueError("Missing MCP stdin pipe")
    body = (json.dumps(payload) + "\n").encode("utf-8")
    stream.write(body)
    stream.flush()


def _read_mcp_response(
    proc: subprocess.Popen[bytes],
    *,
    expected_id: int,
    timeout_seconds: float,
) -> dict | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        message = _read_mcp_message(proc.stdout, timeout_seconds=remaining)
        if message is None:
            return None
        if message.get("id") == expected_id:
            return message
    return None


def _probe_scope_resolution(
    proc: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
) -> dict:
    _write_mcp_message(
        proc.stdin,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_scopes", "arguments": {}},
        },
    )
    list_response = _read_mcp_response(proc, expected_id=3, timeout_seconds=timeout_seconds)
    if list_response is None:
        return {"ok": False, "error": _early_exit_error(proc, "tools/call list_scopes")}
    if "error" in list_response:
        return {"ok": False, "error": list_response["error"].get("message", "list_scopes failed")}

    scopes = _extract_scopes_from_tool_response(list_response.get("result", {}))
    if not scopes:
        return {"ok": True, "status": "no-scopes"}

    _write_mcp_message(
        proc.stdin,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "resolve_scope",
                "arguments": {"scope": scopes[0], "follow_related": False},
            },
        },
    )
    resolve_response = _read_mcp_response(proc, expected_id=4, timeout_seconds=timeout_seconds)
    if resolve_response is None:
        return {"ok": False, "error": _early_exit_error(proc, "tools/call resolve_scope")}
    if "error" in resolve_response:
        return {"ok": False, "error": resolve_response["error"].get("message", "resolve_scope failed")}
    return {"ok": True, "status": "resolved", "scope": scopes[0]}


def _extract_scopes_from_tool_response(result: dict) -> list[str]:
    payload = None
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        payload = structured.get("result")

    if payload is None:
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                payload = first.get("text")

    if not isinstance(payload, str):
        return []

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return []

    scopes = decoded.get("scopes")
    if not isinstance(scopes, list):
        return []
    return [
        scope.get("name")
        for scope in scopes
        if isinstance(scope, dict) and isinstance(scope.get("name"), str)
    ]


def _read_mcp_message(stream, *, timeout_seconds: float) -> dict | None:
    if stream is None:
        return None

    result_queue: queue.Queue[dict | Exception | None] = queue.Queue(maxsize=1)

    def _reader() -> None:
        try:
            line = stream.readline()
            if not line:
                result_queue.put(None)
                return
            result_queue.put(json.loads(line.decode("utf-8")))
        except Exception as exc:  # pragma: no cover - surfaced to caller
            result_queue.put(exc)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    try:
        item = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        return None

    if isinstance(item, Exception):
        raise item
    return item


def _probe_env(repo_root: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DOTSCOPE_ROOT"] = os.path.abspath(repo_root)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["DOTSCOPE_MCP_SESSION_SUMMARY"] = "0"
    env["DOTSCOPE_MCP_VERBOSE"] = "0"
    return env


def _early_exit_error(proc: subprocess.Popen[bytes], phase: str) -> str:
    if proc.poll() is not None:
        return f"MCP server exited before {phase} completed"
    return f"Timed out waiting for MCP {phase} response"


def _safe_stderr(proc: subprocess.Popen[bytes]) -> str:
    if proc.stderr is None:
        return ""
    if proc.poll() is None:
        return ""
    try:
        data = proc.stderr.read() or b""
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    if len(text) <= 400:
        return text
    return text[-400:]


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _format_launch_failure(diagnostics: list[dict]) -> str:
    if not diagnostics:
        return "No dotscope MCP launcher candidates were found"

    lines = ["No working dotscope MCP launcher was found."]
    for item in diagnostics:
        argv = " ".join([item["command"], *item.get("args", [])]).strip()
        reason = item.get("error", "launcher probe failed")
        lines.append(f"- {item.get('source', 'candidate')}: {argv} -> {reason}")
    return "\n".join(lines)


def _print_jetbrains_instructions(repo_root: str, launcher: McpLaunchSpec) -> None:
    """Print manual MCP setup instructions for JetBrains IDEs."""
    argv = launcher.argv(repo_root)
    command = argv[0]
    args = " ".join(argv[1:])
    print(
        "dotscope: JetBrains - add MCP server manually:\n"
        "  Settings > Tools > AI Assistant > MCP\n"
        f"  Command: {command}\n"
        f"  Arguments: {args}",
        file=sys.stderr,
    )


def _print_zed_instructions(repo_root: str, launcher: McpLaunchSpec) -> None:
    """Print manual MCP setup instructions for Zed."""
    argv = launcher.argv(repo_root)
    command = json.dumps(argv[0])
    args = json.dumps(argv[1:])
    print(
        "dotscope: Zed - add to ~/.config/zed/settings.json:\n"
        '  "context_servers": {\n'
        '    "dotscope": {\n'
        '      "source": "custom",\n'
        f"      \"command\": {command},\n"
        f"      \"args\": {args}\n"
        "    }\n"
        "  }",
        file=sys.stderr,
    )
