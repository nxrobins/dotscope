from __future__ import annotations

import json

import pytest

from dotscope.storage.mcp_config import McpBootContractError, McpLaunchSpec, configure_mcp, diagnose_mcp


@pytest.fixture
def launch_spec():
    return McpLaunchSpec(
        command="/abs/path/dotscope-mcp",
        args=(),
        source="managed-runtime",
    )


def _managed_ok_report(repo_root: str, launch_spec: McpLaunchSpec) -> dict:
    return {
        "status": "ok",
        "action": "reused",
        "runtime_root": f"{repo_root}/runtime",
        "launcher_path": launch_spec.command,
        "python_executable": f"{repo_root}/runtime/python",
        "package_spec": "dotscope[mcp]==1.7.9",
        "package_source": "published",
        "source_fingerprint": "fingerprint-123",
        "installed_at": "2026-04-22T00:00:00+00:00",
        "probe": {
            "ok": True,
            "protocol_version": "2025-11-25",
            "tool_count": 14,
            "tools": ["resolve_scope"],
            "scope_probe": {"ok": True, "status": "resolved", "scope": "dotscope"},
            "timings_ms": {"total": 8},
        },
        "timings_ms": {
            "total": 8,
            "initialize": 2,
            "tools_list": 2,
            "list_scopes": 2,
            "resolve_scope": 2,
        },
    }


def test_doctor_repairs_repo_local_targets_and_leaves_global_drift_advisory(
    monkeypatch,
    tmp_path,
    launch_spec,
):
    repo_root = str(tmp_path)
    manifest_path = tmp_path / ".dotscope" / "mcp_install.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"schema_version": 0, "repo_root": repo_root}), encoding="utf-8")

    global_path = tmp_path / "global" / "claude_desktop_config.json"
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(
        json.dumps({"mcpServers": {"dotscope": {"command": "old-launcher", "args": []}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
        lambda _repo_root, probe_func, force_rebuild=False: (
            launch_spec,
            _managed_ok_report(_repo_root, launch_spec),
        ),
    )
    monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: str(global_path))
    monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")
    monkeypatch.setattr("dotscope.storage.mcp_config._iter_launch_candidates", lambda: [])

    report = diagnose_mcp(repo_root)

    assert report["boot_contract_ok"] is True
    assert report["auto_repaired"] is True
    assert all(target["status"] == "ok" for target in report["repo_local_targets"])
    assert report["global_targets"][0]["status"] == "stale"
    assert not any(issue["blocking"] for issue in report["remaining_issues"])
    assert report["next_action"] == "repair_global_if_desired"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["repo_root"] == repo_root
    assert manifest["last_repair_mode"] == "doctor-auto-repair"
    assert manifest["repo_local_targets"][0]["status"] == "ok"
    assert not (tmp_path / ".dotscope" / "mcp_last_failure.json").exists()

    global_config = json.loads(global_path.read_text(encoding="utf-8"))
    assert global_config["mcpServers"]["dotscope"]["command"] == "old-launcher"


def test_doctor_check_is_read_only_and_writes_failure_bundle(monkeypatch, tmp_path, launch_spec):
    repo_root = str(tmp_path)
    stale_repo_config = tmp_path / ".mcp.json"
    stale_repo_config.write_text(
        json.dumps({"mcpServers": {"dotscope": {"command": "old-launcher", "args": []}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "dotscope.storage.mcp_config.diagnose_managed_mcp_runtime",
        lambda _repo_root, probe_func: _managed_ok_report(_repo_root, launch_spec),
    )
    monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: "")
    monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")
    monkeypatch.setattr("dotscope.storage.mcp_config._iter_launch_candidates", lambda: [])

    before = stale_repo_config.read_text(encoding="utf-8")
    report = diagnose_mcp(repo_root, check_only=True)
    after = stale_repo_config.read_text(encoding="utf-8")

    assert before == after
    assert report["boot_contract_ok"] is False
    assert report["auto_repaired"] is False
    assert report["next_action"] == "run_repair"
    assert "dotscope doctor mcp" in report["next_command"]

    bundle_path = tmp_path / ".dotscope" / "mcp_last_failure.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["failing_phase"] == "repo-local-targets"
    assert "dotscope doctor mcp" in bundle["next_command"]
    assert any(target["status"] == "stale" for target in bundle["repo_local_targets"])


def test_doctor_repair_global_updates_supported_global_targets(monkeypatch, tmp_path, launch_spec):
    repo_root = str(tmp_path)
    global_path = tmp_path / "global" / "claude_desktop_config.json"
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(
        json.dumps({"mcpServers": {"dotscope": {"command": "old-launcher", "args": []}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
        lambda _repo_root, probe_func, force_rebuild=False: (
            launch_spec,
            _managed_ok_report(_repo_root, launch_spec),
        ),
    )
    monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: str(global_path))
    monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")
    monkeypatch.setattr("dotscope.storage.mcp_config._iter_launch_candidates", lambda: [])

    report = diagnose_mcp(repo_root, repair_global=True)

    assert report["boot_contract_ok"] is True
    assert report["global_targets"][0]["status"] == "ok"

    global_config = json.loads(global_path.read_text(encoding="utf-8"))
    assert global_config["mcpServers"]["dotscope"]["command"] == launch_spec.command


def test_configure_mcp_raises_with_failure_bundle_when_repo_local_repair_fails(
    monkeypatch,
    tmp_path,
    launch_spec,
):
    repo_root = str(tmp_path)
    original_write_json_config = __import__(
        "dotscope.storage.mcp_config",
        fromlist=["_write_json_config"],
    )._write_json_config

    monkeypatch.setattr(
        "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
        lambda _repo_root, probe_func, force_rebuild=False: (
            launch_spec,
            _managed_ok_report(_repo_root, launch_spec),
        ),
    )
    monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: "")
    monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")
    monkeypatch.setattr("dotscope.storage.mcp_config._iter_launch_candidates", lambda: [])

    def flaky_write_json_config(config_path, *args, **kwargs):
        if config_path.endswith(".mcp.json"):
            raise RuntimeError("permission denied")
        return original_write_json_config(config_path, *args, **kwargs)

    monkeypatch.setattr("dotscope.storage.mcp_config._write_json_config", flaky_write_json_config)

    with pytest.raises(McpBootContractError) as exc:
        configure_mcp(repo_root)

    assert exc.value.report["boot_contract_ok"] is False

    bundle_path = tmp_path / ".dotscope" / "mcp_last_failure.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["root_cause_classification"] == "repo-local-target-drift"
    assert "dotscope init --repair" in bundle["next_command"]
