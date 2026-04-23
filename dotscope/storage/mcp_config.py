"""Auto-detect IDEs and enforce a reliable dotscope MCP boot contract."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import mcp_boot_policy, mcp_probe, mcp_targets
from .atomic import atomic_write_json
from .file_lock import exclusive_file_lock
from .mcp_runtime import (
    McpLaunchSpec,
    diagnose_managed_mcp_runtime,
    ensure_managed_mcp_runtime,
)
from .mcp_targets import McpTargetSpec

_BOOT_LOCK_TIMEOUT_SECONDS = 30.0
_BOOT_CONTRACT_SCHEMA_VERSION = 1
_FAILURE_BUNDLE_RELATIVE_PATH = ".dotscope/mcp_last_failure.json"
_MANIFEST_RELATIVE_PATH = ".dotscope/mcp_install.json"


class McpBootContractError(RuntimeError):
    """Raised when the MCP boot contract remains unhealthy after repair."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def configure_mcp(
    repo_root: str,
    *,
    quiet: bool = False,
    force_repair: bool = False,
) -> list[str]:
    """Ensure the managed runtime and generated MCP configs are healthy."""
    report = evaluate_mcp_boot_contract(
        repo_root,
        command="init",
        check_only=False,
        repair_global=True,
        force_repair=force_repair,
        quiet=quiet,
    )
    if not report["boot_contract_ok"]:
        raise McpBootContractError(_format_boot_contract_failure(report), report)
    return report["configured_labels"]


def diagnose_mcp(
    repo_root: str,
    *,
    check_only: bool = False,
    repair_global: bool = False,
) -> dict:
    """Inspect or repair the MCP boot contract for a repository."""
    return evaluate_mcp_boot_contract(
        repo_root,
        command="doctor",
        check_only=check_only,
        repair_global=repair_global,
        force_repair=False,
        quiet=False,
    )


def evaluate_mcp_boot_contract(
    repo_root: str,
    *,
    command: str,
    check_only: bool,
    repair_global: bool,
    force_repair: bool,
    quiet: bool,
) -> dict:
    """Run the shared MCP runtime/config boot contract pipeline."""
    if check_only and repair_global:
        raise ValueError("`dotscope doctor mcp --check` cannot be combined with `--repair-global`")

    repo_root = os.path.abspath(repo_root)
    manifest_path = _boot_manifest_path(repo_root)
    failure_path = _boot_failure_path(repo_root)
    timings: dict[str, int] = {}
    total_start = time.monotonic()
    configured_labels: list[str] = []
    repair_errors: dict[str, str] = {}
    auto_repaired = False
    runtime_error: str | None = None

    runtime_start = time.monotonic()
    managed = {}
    launcher = None
    try:
        if check_only:
            managed = diagnose_managed_mcp_runtime(repo_root, probe_func=probe_mcp_launch)
        else:
            runtime_force_rebuild = force_repair and command == "init"
            launcher, managed = ensure_managed_mcp_runtime(
                repo_root,
                probe_func=probe_mcp_launch,
                force_rebuild=runtime_force_rebuild,
            )
    except RuntimeError as exc:
        runtime_error = str(exc)
        managed = diagnose_managed_mcp_runtime(repo_root, probe_func=probe_mcp_launch)
        managed["error"] = runtime_error
    timings["runtime_total"] = _ms_since(runtime_start)

    launcher = launcher or _launcher_from_managed(managed)
    entry = _build_json_entry(launcher, repo_root) if launcher else None

    inspect_start = time.monotonic()
    repo_specs = _repo_local_target_specs(repo_root)
    global_specs = _global_target_specs(repo_root)
    repo_local_targets = [_inspect_target(spec, entry, launcher, repo_root) for spec in repo_specs]
    global_targets = [_inspect_target(spec, entry, launcher, repo_root) for spec in global_specs]
    timings["inspect_targets"] = _ms_since(inspect_start)

    should_write_global = command == "init" or repair_global
    enforce_global = repair_global and command == "doctor"

    if launcher and not check_only:
        if _needs_repairs(repo_local_targets, force_repair):
            repo_write_start = time.monotonic()
            with exclusive_file_lock(_boot_lock_path(repo_root), timeout_seconds=_BOOT_LOCK_TIMEOUT_SECONDS):
                labels, errors = _repair_targets(
                    repo_specs,
                    repo_local_targets,
                    entry,
                    launcher,
                    repo_root,
                    force_repair=force_repair,
                )
                configured_labels.extend(labels)
                repair_errors.update(errors)
            timings["repo_target_writes"] = _ms_since(repo_write_start)

        if should_write_global and _needs_repairs(global_targets, force_repair):
            global_write_start = time.monotonic()
            labels, errors = _repair_targets(
                global_specs,
                global_targets,
                entry,
                launcher,
                repo_root,
                force_repair=force_repair,
            )
            configured_labels.extend(labels)
            repair_errors.update(errors)
            timings["global_target_writes"] = _ms_since(global_write_start)

        auto_repaired = bool(configured_labels) or managed.get("action") in {"installed", "repaired"}

        recheck_start = time.monotonic()
        repo_local_targets = [_inspect_target(spec, entry, launcher, repo_root) for spec in repo_specs]
        global_targets = [_inspect_target(spec, entry, launcher, repo_root) for spec in global_specs]
        timings["reinspect_targets"] = _ms_since(recheck_start)

    _apply_repair_errors(repo_local_targets + global_targets, repair_errors)

    candidates = _ambient_candidates_for_report(repo_root, managed)
    timings["contract_total"] = _ms_since(total_start)
    if managed.get("timings_ms"):
        timings["probe_total"] = managed["timings_ms"].get("total", 0)
        timings["probe_initialize"] = managed["timings_ms"].get("initialize", 0)
        timings["probe_tools_list"] = managed["timings_ms"].get("tools_list", 0)
        timings["probe_list_scopes"] = managed["timings_ms"].get("list_scopes", 0)
        timings["probe_resolve_scope"] = managed["timings_ms"].get("resolve_scope", 0)

    remaining_issues = _collect_remaining_issues(
        managed=managed,
        runtime_error=runtime_error,
        repo_local_targets=repo_local_targets,
        global_targets=global_targets,
        enforce_global=enforce_global,
    )
    boot_contract_ok = not any(issue["blocking"] for issue in remaining_issues)
    next_action, next_command = _next_repair_step(
        command=command,
        check_only=check_only,
        repair_global=repair_global,
        force_repair=force_repair,
        issues=remaining_issues,
        repo_root=repo_root,
    )

    report = {
        "repo_root": repo_root,
        "schema_version": _BOOT_CONTRACT_SCHEMA_VERSION,
        "boot_contract_ok": boot_contract_ok,
        "auto_repaired": auto_repaired,
        "configured_labels": configured_labels,
        "repair_mode": _repair_mode(command, check_only, repair_global, force_repair),
        "launcher": {
            "ok": launcher is not None,
            "command": launcher.command if launcher else None,
            "args": list(launcher.args) if launcher else [],
            "source": launcher.source if launcher else None,
        },
        "managed_runtime": managed,
        "candidates": candidates,
        "repo_local_targets": repo_local_targets,
        "global_targets": global_targets,
        "targets": [*repo_local_targets, *global_targets],
        "remaining_issues": remaining_issues,
        "timings_ms": timings,
        "manifest_path": str(manifest_path),
        "last_failure_path": str(failure_path),
        "next_action": next_action,
        "next_command": next_command,
        "notes": [
            "Repo-local MCP targets are enforced by the boot contract.",
            "Global client configs remain advisory unless `--repair-global` is requested.",
            "Some clients still require an explicit trust or approval prompt before they start a configured server.",
        ],
    }

    if boot_contract_ok:
        _clear_failure_bundle(repo_root)
        _write_boot_manifest(repo_root, report)
    else:
        _write_failure_bundle(repo_root, report)

    return report


def format_mcp_failure_footer(report: dict) -> str:
    """Return the standard stderr footer for failed MCP boot commands."""
    footer = (
        "BOOT CONTRACT FAILED. Auto-repair was insufficient. "
        f"Read {_FAILURE_BUNDLE_RELATIVE_PATH} for diagnostics and exact repair steps."
    )
    if report.get("next_command"):
        footer += f" Next command: {report['next_command']}"
    return footer


def collect_mcp_launch_diagnostics(repo_root: str) -> tuple[McpLaunchSpec | None, list[dict]]:
    """Return the first working launcher plus probe details for all ambient candidates."""
    return mcp_probe.collect_mcp_launch_diagnostics(
        repo_root,
        iter_launch_candidates=_iter_launch_candidates,
        probe_func=probe_mcp_launch,
    )


def probe_mcp_launch(
    launcher: McpLaunchSpec,
    repo_root: str,
    timeout_seconds: float = mcp_probe._DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> dict:
    """Exercise a launcher with a real initialize/tools-list handshake."""
    return mcp_probe.probe_mcp_launch(launcher, repo_root, timeout_seconds=timeout_seconds)


def _claude_desktop_config_path() -> str:
    return mcp_targets._claude_desktop_config_path()


def _windsurf_config_path() -> str:
    return mcp_targets._windsurf_config_path()


def _build_json_entry(launcher: McpLaunchSpec | None, repo_root: str) -> dict | None:
    return mcp_targets._build_json_entry(launcher, repo_root)


def _write_json_config(
    config_path: str,
    top_key: str,
    entry: dict,
    *,
    allow_legacy_flat: bool = False,
    repair_invalid: bool = False,
    force: bool = False,
) -> bool:
    return mcp_targets._write_json_config(
        config_path,
        top_key,
        entry,
        allow_legacy_flat=allow_legacy_flat,
        repair_invalid=repair_invalid,
        force=force,
    )


def _write_cursor_config(
    config_path: str,
    entry: dict,
    *,
    repair_invalid: bool = False,
    force: bool = False,
) -> bool:
    return mcp_targets._write_cursor_config(
        config_path,
        entry,
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
    return mcp_targets._write_codex_toml(config_path, launcher, repo_root, force=force)


def _inspect_json_target(
    label: str,
    path: str,
    top_key: str,
    expected_entry: dict | None,
    *,
    allow_legacy_flat: bool = False,
) -> dict:
    return mcp_targets._inspect_json_target(
        label,
        path,
        top_key,
        expected_entry,
        allow_legacy_flat=allow_legacy_flat,
    )


def _inspect_codex_target(
    label: str,
    path: str,
    launcher: McpLaunchSpec | None,
    repo_root: str,
) -> dict:
    return mcp_targets._inspect_codex_target(label, path, launcher, repo_root)


def _load_json_config(config_path: str, *, repair_invalid: bool = False) -> dict:
    return mcp_targets._load_json_config(config_path, repair_invalid=repair_invalid)


def _looks_like_legacy_flat_server_map(config: dict) -> bool:
    return mcp_targets._looks_like_legacy_flat_server_map(config)


def _render_codex_block(launcher: McpLaunchSpec, repo_root: str) -> str:
    return mcp_targets._render_codex_block(launcher, repo_root)


def _iter_launch_candidates() -> list[McpLaunchSpec]:
    return mcp_probe.iter_launch_candidates()


def _repo_local_target_specs(repo_root: str) -> list[McpTargetSpec]:
    return mcp_boot_policy.repo_local_target_specs(repo_root)


def _global_target_specs(repo_root: str) -> list[McpTargetSpec]:
    del repo_root
    return mcp_boot_policy.global_target_specs(
        claude_desktop_config_path=_claude_desktop_config_path,
        windsurf_config_path=_windsurf_config_path,
    )


def _inspect_target(
    spec: McpTargetSpec,
    entry: dict | None,
    launcher: McpLaunchSpec | None,
    repo_root: str,
) -> dict:
    return mcp_boot_policy.inspect_target(spec, entry, launcher, repo_root)


def _repair_targets(
    specs: list[McpTargetSpec],
    targets: list[dict],
    entry: dict,
    launcher: McpLaunchSpec,
    repo_root: str,
    *,
    force_repair: bool,
) -> tuple[list[str], dict[str, str]]:
    return mcp_boot_policy.repair_targets(
        specs,
        targets,
        entry,
        launcher,
        repo_root,
        force_repair=force_repair,
        repair_target=_repair_target,
    )


def _repair_target(
    spec: McpTargetSpec,
    entry: dict,
    launcher: McpLaunchSpec,
    repo_root: str,
    *,
    force: bool,
) -> bool:
    return mcp_boot_policy.repair_target(
        spec,
        entry,
        launcher,
        repo_root,
        force=force,
        write_json_config=_write_json_config,
        write_cursor_config=_write_cursor_config,
        write_codex_toml=_write_codex_toml,
    )


def _needs_repairs(targets: list[dict], force_repair: bool) -> bool:
    return mcp_boot_policy.needs_repairs(targets, force_repair)


def _apply_repair_errors(targets: list[dict], repair_errors: dict[str, str]) -> None:
    mcp_boot_policy.apply_repair_errors(targets, repair_errors)


def _collect_remaining_issues(
    *,
    managed: dict,
    runtime_error: str | None,
    repo_local_targets: list[dict],
    global_targets: list[dict],
    enforce_global: bool,
) -> list[dict]:
    return mcp_boot_policy.collect_remaining_issues(
        managed=managed,
        runtime_error=runtime_error,
        repo_local_targets=repo_local_targets,
        global_targets=global_targets,
        enforce_global=enforce_global,
    )


def _issue_from_target(target: dict, *, blocking: bool) -> dict:
    return mcp_boot_policy.issue_from_target(target, blocking=blocking)


def _repair_mode(command: str, check_only: bool, repair_global: bool, force_repair: bool) -> str:
    return mcp_boot_policy.repair_mode(command, check_only, repair_global, force_repair)


def _next_repair_step(
    *,
    command: str,
    check_only: bool,
    repair_global: bool,
    force_repair: bool,
    issues: list[dict],
    repo_root: str,
) -> tuple[str, str]:
    return mcp_boot_policy.next_repair_step(
        command=command,
        check_only=check_only,
        repair_global=repair_global,
        force_repair=force_repair,
        issues=issues,
        repo_root=repo_root,
    )


def _rooted_command(parts: list[str], repo_root: str) -> str:
    return mcp_boot_policy.rooted_command(parts, repo_root)


def _quote_cli_arg(value: str) -> str:
    return mcp_boot_policy.quote_cli_arg(value)


def _launcher_from_managed(managed: dict) -> McpLaunchSpec | None:
    launcher_path = managed.get("launcher_path")
    if not launcher_path:
        return None
    return McpLaunchSpec(command=launcher_path, args=(), source="managed-runtime")


def _ambient_candidates_for_report(repo_root: str, managed: dict) -> list[dict]:
    del repo_root
    selected_path = managed.get("launcher_path")
    probe = managed.get("probe") if isinstance(managed.get("probe"), dict) else {}

    candidates: list[dict] = []
    seen = set()
    for candidate in _iter_launch_candidates():
        key = (candidate.command, candidate.args)
        if key in seen:
            continue
        seen.add(key)
        item = {
            "command": candidate.command,
            "args": list(candidate.args),
            "source": candidate.source,
            "ok": None,
        }
        if candidate.command == selected_path:
            item["ok"] = probe.get("ok", managed.get("status") == "ok")
            if probe.get("error"):
                item["error"] = probe["error"]
            if probe.get("tool_count") is not None:
                item["tool_count"] = probe.get("tool_count")
            if probe.get("tools") is not None:
                item["tools"] = probe.get("tools")
        candidates.append(item)

    if not candidates and selected_path:
        candidates.append(
            {
                "command": selected_path,
                "args": [],
                "source": "managed-runtime",
                "ok": probe.get("ok", managed.get("status") == "ok"),
                "error": probe.get("error"),
            }
        )

    return candidates


def _boot_state_dir(repo_root: str) -> Path:
    return Path(repo_root) / ".dotscope"


def _boot_lock_path(repo_root: str) -> Path:
    return _boot_state_dir(repo_root) / ".mcp_boot.lock"


def _boot_manifest_path(repo_root: str) -> Path:
    return _boot_state_dir(repo_root) / "mcp_install.json"


def _boot_failure_path(repo_root: str) -> Path:
    return _boot_state_dir(repo_root) / "mcp_last_failure.json"


def _write_boot_manifest(repo_root: str, report: dict) -> None:
    with exclusive_file_lock(_boot_lock_path(repo_root), timeout_seconds=_BOOT_LOCK_TIMEOUT_SECONDS):
        atomic_write_json(_boot_manifest_path(repo_root), _boot_manifest_payload(report))


def _write_failure_bundle(repo_root: str, report: dict) -> None:
    with exclusive_file_lock(_boot_lock_path(repo_root), timeout_seconds=_BOOT_LOCK_TIMEOUT_SECONDS):
        atomic_write_json(_boot_failure_path(repo_root), _failure_bundle_payload(report))


def _clear_failure_bundle(repo_root: str) -> None:
    path = _boot_failure_path(repo_root)
    with exclusive_file_lock(_boot_lock_path(repo_root), timeout_seconds=_BOOT_LOCK_TIMEOUT_SECONDS):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return


def _boot_manifest_payload(report: dict) -> dict:
    managed = report.get("managed_runtime", {})
    launcher = report.get("launcher", {})
    probe = managed.get("probe") if isinstance(managed.get("probe"), dict) else {}
    selected_launcher = None
    if launcher.get("command"):
        selected_launcher = {
            "command": launcher.get("command"),
            "args": [*launcher.get("args", []), "--root", report["repo_root"]],
            "source": launcher.get("source"),
        }

    return {
        "schema_version": _BOOT_CONTRACT_SCHEMA_VERSION,
        "repo_root": report["repo_root"],
        "selected_launcher": selected_launcher,
        "managed_runtime": {
            "status": managed.get("status"),
            "runtime_root": managed.get("runtime_root"),
            "python_executable": managed.get("python_executable"),
            "launcher_path": managed.get("launcher_path"),
            "package_spec": managed.get("package_spec"),
            "package_source": managed.get("package_source"),
            "source_fingerprint": managed.get("source_fingerprint") or managed.get("desired_source_fingerprint"),
            "installed_at": managed.get("installed_at"),
        },
        "last_successful_verification": {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "protocol_version": probe.get("protocol_version"),
            "tool_count": probe.get("tool_count"),
            "tools": probe.get("tools"),
            "scope_probe": probe.get("scope_probe"),
        },
        "probe_timings_ms": report.get("timings_ms", {}),
        "repo_local_targets": report.get("repo_local_targets", []),
        "global_targets": report.get("global_targets", []),
        "last_repair_mode": report.get("repair_mode"),
    }


def _failure_bundle_payload(report: dict) -> dict:
    return {
        "schema_version": _BOOT_CONTRACT_SCHEMA_VERSION,
        "repo_root": report["repo_root"],
        "failing_phase": _failing_phase(report),
        "launcher_argv": _report_launcher_argv(report),
        "protocol_attempts": _report_protocol_attempts(report),
        "stderr_snippet": _report_stderr(report),
        "timings_ms": report.get("timings_ms", {}),
        "repo_local_targets": report.get("repo_local_targets", []),
        "global_targets": report.get("global_targets", []),
        "target_statuses": report.get("targets", []),
        "root_cause_classification": _classify_failure(report),
        "remaining_issues": report.get("remaining_issues", []),
        "next_action": report.get("next_action"),
        "next_command": report.get("next_command"),
    }


def _failing_phase(report: dict) -> str:
    if any(issue.get("scope") == "runtime" and issue.get("blocking") for issue in report.get("remaining_issues", [])):
        return "managed-runtime"
    if any(issue.get("scope") == "repo-local" and issue.get("blocking") for issue in report.get("remaining_issues", [])):
        return "repo-local-targets"
    if any(issue.get("scope") == "global" and issue.get("blocking") for issue in report.get("remaining_issues", [])):
        return "global-targets"
    return "boot-contract"


def _classify_failure(report: dict) -> str:
    if report.get("managed_runtime", {}).get("status") != "ok":
        return "managed-runtime"
    if any(issue.get("scope") == "repo-local" and issue.get("blocking") for issue in report.get("remaining_issues", [])):
        return "repo-local-target-drift"
    if any(issue.get("scope") == "global" for issue in report.get("remaining_issues", [])):
        return "global-target-drift"
    return "unknown"


def _report_launcher_argv(report: dict) -> list[str]:
    launcher = report.get("launcher", {})
    command = launcher.get("command")
    if not command:
        return []
    return [command, *launcher.get("args", []), "--root", report["repo_root"]]


def _report_protocol_attempts(report: dict) -> list[dict]:
    managed = report.get("managed_runtime", {})
    probe = managed.get("probe")
    if isinstance(probe, dict) and isinstance(probe.get("attempts"), list):
        return probe["attempts"]
    if isinstance(managed.get("attempts"), list):
        return managed["attempts"]
    return []


def _report_stderr(report: dict) -> str:
    managed = report.get("managed_runtime", {})
    probe = managed.get("probe")
    if isinstance(probe, dict) and probe.get("stderr"):
        return probe["stderr"]
    if managed.get("error"):
        return str(managed["error"])
    return ""


def _format_boot_contract_failure(report: dict) -> str:
    blocking = [issue["message"] for issue in report.get("remaining_issues", []) if issue.get("blocking")]
    if not blocking:
        blocking = [issue["message"] for issue in report.get("remaining_issues", [])]
    if not blocking:
        return "MCP boot contract failed."
    summary = "; ".join(blocking[:3])
    return f"MCP boot contract failed: {summary}"


def _status_requires_attention(status: str) -> bool:
    return mcp_boot_policy.status_requires_attention(status)

def _ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
