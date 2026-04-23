"""Boot-contract target policy helpers for MCP runtime/config enforcement."""

from __future__ import annotations

import os
import shlex
from typing import Callable

from . import mcp_targets
from .mcp_runtime import McpLaunchSpec
from .mcp_targets import McpTargetSpec


def repo_local_target_specs(repo_root: str) -> list[McpTargetSpec]:
    return [
        McpTargetSpec(
            label="Claude Code (.mcp.json)",
            scope="repo-local",
            kind="json",
            path=os.path.join(repo_root, ".mcp.json"),
            top_key="mcpServers",
        ),
        McpTargetSpec(
            label="Claude Code (legacy workspace)",
            scope="repo-local",
            kind="json",
            path=os.path.join(repo_root, ".claude", "settings.json"),
            top_key="mcpServers",
        ),
        McpTargetSpec(
            label="VS Code Copilot",
            scope="repo-local",
            kind="json",
            path=os.path.join(repo_root, ".vscode", "mcp.json"),
            top_key="servers",
        ),
        McpTargetSpec(
            label="Cursor",
            scope="repo-local",
            kind="cursor",
            path=os.path.join(repo_root, ".cursor", "mcp.json"),
        ),
        McpTargetSpec(
            label="Codex CLI",
            scope="repo-local",
            kind="codex",
            path=os.path.join(repo_root, ".codex", "config.toml"),
        ),
    ]


def global_target_specs(
    *,
    claude_desktop_config_path: Callable[[], str],
    windsurf_config_path: Callable[[], str],
) -> list[McpTargetSpec]:
    specs: list[McpTargetSpec] = []

    claude_path = claude_desktop_config_path()
    if claude_path:
        specs.append(
            McpTargetSpec(
                label="Claude Desktop",
                scope="global",
                kind="json",
                path=claude_path,
                top_key="mcpServers",
            )
        )

    windsurf_path = windsurf_config_path()
    if windsurf_path:
        specs.append(
            McpTargetSpec(
                label="Windsurf",
                scope="global",
                kind="json",
                path=windsurf_path,
                top_key="mcpServers",
            )
        )

    return specs


def inspect_target(
    spec: McpTargetSpec,
    entry: dict | None,
    launcher: McpLaunchSpec | None,
    repo_root: str,
) -> dict:
    if spec.kind == "json":
        target = mcp_targets._inspect_json_target(
            spec.label,
            spec.path,
            spec.top_key or "mcpServers",
            entry,
            allow_legacy_flat=spec.allow_legacy_flat,
        )
    elif spec.kind == "cursor":
        target = mcp_targets._inspect_json_target(
            spec.label,
            spec.path,
            "mcpServers",
            entry,
            allow_legacy_flat=True,
        )
    elif spec.kind == "codex":
        target = mcp_targets._inspect_codex_target(spec.label, spec.path, launcher, repo_root)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported MCP target kind: {spec.kind}")

    target["scope"] = spec.scope
    target["kind"] = spec.kind
    target["repairable"] = status_requires_attention(target.get("status", ""))
    return target


def repair_targets(
    specs: list[McpTargetSpec],
    targets: list[dict],
    entry: dict,
    launcher: McpLaunchSpec,
    repo_root: str,
    *,
    force_repair: bool,
    repair_target: Callable[..., bool],
) -> tuple[list[str], dict[str, str]]:
    configured: list[str] = []
    errors: dict[str, str] = {}

    for spec, target in zip(specs, targets):
        if not spec.path or target.get("status") == "unavailable":
            continue
        if not force_repair and not status_requires_attention(target.get("status", "")):
            continue
        try:
            if repair_target(spec, entry, launcher, repo_root, force=force_repair):
                configured.append(spec.label)
        except Exception as exc:  # pragma: no cover - surfaced through report
            errors[spec.label] = str(exc)

    return configured, errors


def repair_target(
    spec: McpTargetSpec,
    entry: dict,
    launcher: McpLaunchSpec,
    repo_root: str,
    *,
    force: bool,
    write_json_config: Callable[..., bool],
    write_cursor_config: Callable[..., bool],
    write_codex_toml: Callable[..., bool],
) -> bool:
    if spec.kind == "json":
        return write_json_config(
            spec.path,
            spec.top_key or "mcpServers",
            entry,
            allow_legacy_flat=spec.allow_legacy_flat,
            repair_invalid=True,
            force=force,
        )
    if spec.kind == "cursor":
        return write_cursor_config(spec.path, entry, repair_invalid=True, force=force)
    if spec.kind == "codex":
        return write_codex_toml(spec.path, launcher, repo_root, force=force)
    raise ValueError(f"Unsupported MCP target kind: {spec.kind}")


def needs_repairs(targets: list[dict], force_repair: bool) -> bool:
    return force_repair or any(status_requires_attention(target.get("status", "")) for target in targets)


def apply_repair_errors(targets: list[dict], repair_errors: dict[str, str]) -> None:
    for target in targets:
        error = repair_errors.get(target.get("label", ""))
        if error:
            target["error"] = error


def collect_remaining_issues(
    *,
    managed: dict,
    runtime_error: str | None,
    repo_local_targets: list[dict],
    global_targets: list[dict],
    enforce_global: bool,
) -> list[dict]:
    issues: list[dict] = []

    runtime_status = managed.get("status", "missing")
    if runtime_status != "ok":
        details = runtime_error or managed.get("error")
        if not details:
            probe = managed.get("probe")
            if isinstance(probe, dict):
                details = probe.get("error")
        message = f"Managed runtime is {runtime_status}"
        if details:
            message = f"{message}: {details}"
        issues.append(
            {
                "category": "managed-runtime",
                "scope": "runtime",
                "label": "Managed runtime",
                "status": runtime_status,
                "blocking": True,
                "message": message,
                "path": managed.get("runtime_root"),
            }
        )

    for target in repo_local_targets:
        if status_requires_attention(target.get("status", "")):
            issues.append(issue_from_target(target, blocking=True))

    for target in global_targets:
        if status_requires_attention(target.get("status", "")):
            issues.append(issue_from_target(target, blocking=enforce_global))

    return issues


def issue_from_target(target: dict, *, blocking: bool) -> dict:
    status = target.get("status", "unknown")
    label = target.get("label", "MCP target")
    message = f"{label} is {status}"
    if target.get("error"):
        message = f"{message}: {target['error']}"
    return {
        "category": "target",
        "scope": target.get("scope"),
        "label": label,
        "status": status,
        "blocking": blocking,
        "message": message,
        "path": target.get("path"),
    }


def repair_mode(command: str, check_only: bool, repair_global: bool, force_repair: bool) -> str:
    if command == "init" and force_repair:
        return "init-force-repair"
    if command == "init":
        return "init"
    if check_only:
        return "doctor-check"
    if repair_global:
        return "doctor-repair-global"
    return "doctor-auto-repair"


def next_repair_step(
    *,
    command: str,
    check_only: bool,
    repair_global: bool,
    force_repair: bool,
    issues: list[dict],
    repo_root: str,
) -> tuple[str, str]:
    blocking = [issue for issue in issues if issue.get("blocking")]
    advisory_global = [
        issue
        for issue in issues
        if issue.get("scope") == "global" and not issue.get("blocking")
    ]
    if not blocking:
        if advisory_global and not repair_global:
            return (
                "repair_global_if_desired",
                rooted_command(["dotscope", "doctor", "mcp", "--repair-global"], repo_root),
            )
        return "none", ""

    if command == "init":
        if force_repair:
            return (
                "inspect_diagnostics",
                rooted_command(["dotscope", "doctor", "mcp", "--json"], repo_root),
            )
        return (
            "force_repair",
            rooted_command(["dotscope", "init", "--repair"], repo_root),
        )

    if check_only:
        return "run_repair", rooted_command(["dotscope", "doctor", "mcp"], repo_root)

    if repair_global:
        return (
            "inspect_diagnostics",
            rooted_command(["dotscope", "doctor", "mcp", "--repair-global", "--json"], repo_root),
        )

    return "run_repair", rooted_command(["dotscope", "doctor", "mcp"], repo_root)


def rooted_command(parts: list[str], repo_root: str) -> str:
    return " ".join([*parts, quote_cli_arg(repo_root)])


def quote_cli_arg(value: str) -> str:
    if os.name == "nt":
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return shlex.quote(value)


def status_requires_attention(status: str) -> bool:
    return status in {"missing", "stale", "error", "legacy-flat"}
