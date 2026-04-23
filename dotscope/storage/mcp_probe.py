"""Low-level MCP launcher discovery and stdio self-test helpers."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path
from typing import Callable

from .mcp_runtime import McpLaunchSpec

_MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0


def collect_mcp_launch_diagnostics(
    repo_root: str,
    *,
    iter_launch_candidates: Callable[[], list[McpLaunchSpec]],
    probe_func: Callable[[McpLaunchSpec, str], dict],
) -> tuple[McpLaunchSpec | None, list[dict]]:
    """Return the first working launcher plus probe details for all ambient candidates."""
    repo_root = os.path.abspath(repo_root)
    selected: McpLaunchSpec | None = None
    diagnostics: list[dict] = []

    for candidate in iter_launch_candidates():
        probe = probe_func(candidate, repo_root)
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

    last = failures[-1] if failures else {"error": "No protocol versions attempted", "timings_ms": {}}
    return {
        "ok": False,
        "error": last.get("error", "No working MCP response"),
        "stderr": last.get("stderr", ""),
        "timings_ms": last.get("timings_ms", {}),
        "attempts": failures,
    }


def iter_launch_candidates() -> list[McpLaunchSpec]:
    """Return candidate launchers discovered from the current environment."""
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
    probe_start = time.monotonic()
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
        return {
            "ok": False,
            "error": str(exc),
            "stderr": "",
            "protocol_version": protocol_version,
            "timings_ms": {"total": _ms_since(probe_start)},
        }

    timings: dict[str, int] = {}
    try:
        init_start = time.monotonic()
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
        timings["initialize"] = _ms_since(init_start)
        if init_response is None:
            return {
                "ok": False,
                "error": _early_exit_error(proc, "initialize"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
                "timings_ms": _finalize_probe_timings(timings, probe_start),
            }
        if "error" in init_response:
            return {
                "ok": False,
                "error": init_response["error"].get("message", "initialize failed"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
                "timings_ms": _finalize_probe_timings(timings, probe_start),
            }

        _write_mcp_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )

        tools_start = time.monotonic()
        _write_mcp_message(
            proc.stdin,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_response = _read_mcp_response(proc, expected_id=2, timeout_seconds=timeout_seconds)
        timings["tools_list"] = _ms_since(tools_start)
        if tools_response is None:
            return {
                "ok": False,
                "error": _early_exit_error(proc, "tools/list"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
                "timings_ms": _finalize_probe_timings(timings, probe_start),
            }
        if "error" in tools_response:
            return {
                "ok": False,
                "error": tools_response["error"].get("message", "tools/list failed"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
                "timings_ms": _finalize_probe_timings(timings, probe_start),
            }

        tools = tools_response.get("result", {}).get("tools", [])
        names = [tool.get("name") for tool in tools if isinstance(tool, dict) and tool.get("name")]
        scope_probe = _probe_scope_resolution(proc, timeout_seconds=timeout_seconds)
        timings.update(scope_probe.get("timings_ms", {}))
        if not scope_probe.get("ok"):
            return {
                "ok": False,
                "error": scope_probe.get("error", "scope probe failed"),
                "stderr": _safe_stderr(proc),
                "protocol_version": protocol_version,
                "tool_count": len(names),
                "tools": names[:8],
                "timings_ms": _finalize_probe_timings(timings, probe_start),
            }
        return {
            "ok": True,
            "protocol_version": protocol_version,
            "tool_count": len(names),
            "tools": names[:8],
            "scope_probe": {k: v for k, v in scope_probe.items() if k != "timings_ms"},
            "stderr": _safe_stderr(proc),
            "timings_ms": _finalize_probe_timings(timings, probe_start),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "stderr": _safe_stderr(proc),
            "protocol_version": protocol_version,
            "timings_ms": _finalize_probe_timings(timings, probe_start),
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
    timings: dict[str, int] = {}

    list_start = time.monotonic()
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
    timings["list_scopes"] = _ms_since(list_start)
    if list_response is None:
        return {
            "ok": False,
            "error": _early_exit_error(proc, "tools/call list_scopes"),
            "timings_ms": timings,
        }
    if "error" in list_response:
        return {
            "ok": False,
            "error": list_response["error"].get("message", "list_scopes failed"),
            "timings_ms": timings,
        }

    scopes = _extract_scopes_from_tool_response(list_response.get("result", {}))
    if not scopes:
        return {"ok": True, "status": "no-scopes", "timings_ms": timings}

    resolve_start = time.monotonic()
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
    timings["resolve_scope"] = _ms_since(resolve_start)
    if resolve_response is None:
        return {
            "ok": False,
            "error": _early_exit_error(proc, "tools/call resolve_scope"),
            "timings_ms": timings,
        }
    if "error" in resolve_response:
        return {
            "ok": False,
            "error": resolve_response["error"].get("message", "resolve_scope failed"),
            "timings_ms": timings,
        }
    return {"ok": True, "status": "resolved", "scope": scopes[0], "timings_ms": timings}


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


def _terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _finalize_probe_timings(timings: dict[str, int], probe_start: float) -> dict[str, int]:
    finalized = dict(timings)
    finalized["total"] = _ms_since(probe_start)
    return finalized
