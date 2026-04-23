"""Tests for the managed MCP runtime installer/state layer."""

from __future__ import annotations

import json
from pathlib import Path

from dotscope import __version__
from dotscope.storage.mcp_runtime import (
    ManagedRuntimeState,
    diagnose_managed_mcp_runtime,
    ensure_managed_mcp_runtime,
    load_managed_runtime_state,
    managed_runtime_lock_path,
    managed_runtime_launcher_path,
    managed_runtime_python_path,
    resolve_managed_package_details,
    resolve_managed_package_spec,
)


def test_resolve_managed_package_spec_uses_env_override(monkeypatch):
    monkeypatch.setenv("DOTSCOPE_MCP_PACKAGE_SPEC", "dotscope[mcp]==9.9.9")
    spec, source = resolve_managed_package_spec()
    assert spec == "dotscope[mcp]==9.9.9"
    assert source == "env-override"


def test_resolve_managed_package_details_uses_env_override(monkeypatch):
    monkeypatch.setenv("DOTSCOPE_MCP_PACKAGE_SPEC", "dotscope[mcp]==9.9.9")
    spec, source, fingerprint = resolve_managed_package_details()
    assert spec == "dotscope[mcp]==9.9.9"
    assert source == "env-override"
    assert fingerprint == "dotscope[mcp]==9.9.9"


def test_ensure_managed_runtime_writes_state(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DOTSCOPE_MCP_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setattr(
        "dotscope.storage.mcp_runtime.resolve_managed_package_details",
        lambda: ("dotscope[mcp]==1.2.3", "published", "fingerprint-123"),
    )

    def fake_rebuild(root: Path) -> None:
        python_path = managed_runtime_python_path(root)
        launcher_path = managed_runtime_launcher_path(root)
        python_path.parent.mkdir(parents=True, exist_ok=True)
        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")
        launcher_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("dotscope.storage.mcp_runtime._rebuild_managed_runtime", fake_rebuild)
    monkeypatch.setattr("dotscope.storage.mcp_runtime._install_runtime_package", lambda *_args, **_kwargs: None)

    def fake_probe(launcher, repo_root):
        assert launcher.command == str(managed_runtime_launcher_path(runtime_root))
        assert repo_root == str(tmp_path)
        return {"ok": True, "tool_count": 13, "scope_probe": {"ok": True, "status": "resolved", "scope": "auth"}}

    launcher, report = ensure_managed_mcp_runtime(str(tmp_path), probe_func=fake_probe)

    assert launcher.command == str(managed_runtime_launcher_path(runtime_root))
    assert report["status"] == "ok"
    state = load_managed_runtime_state()
    assert state is not None
    assert state.package_spec == "dotscope[mcp]==1.2.3"
    assert state.source_fingerprint == "fingerprint-123"
    assert Path(state.python_executable).exists()
    assert Path(state.launcher_path).exists()


def test_ensure_managed_runtime_reuses_working_state(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DOTSCOPE_MCP_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setattr(
        "dotscope.storage.mcp_runtime.resolve_managed_package_details",
        lambda: ("dotscope[mcp]==1.2.3", "published", "fingerprint-123"),
    )

    python_path = managed_runtime_python_path(runtime_root)
    launcher_path = managed_runtime_launcher_path(runtime_root)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    launcher_path.write_text("", encoding="utf-8")

    state = ManagedRuntimeState(
        dotscope_version=__version__,
        runtime_root=str(runtime_root),
        python_executable=str(python_path),
        launcher_path=str(launcher_path),
        package_spec="dotscope[mcp]==1.2.3",
        package_source="published",
        installed_at="2026-04-22T00:00:00+00:00",
        source_fingerprint="fingerprint-123",
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "install.json").write_text(json.dumps(state.__dict__), encoding="utf-8")

    monkeypatch.setattr(
        "dotscope.storage.mcp_runtime._rebuild_managed_runtime",
        lambda _root: (_ for _ in ()).throw(AssertionError("should not rebuild")),
    )
    monkeypatch.setattr(
        "dotscope.storage.mcp_runtime._install_runtime_package",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not reinstall")),
    )

    launcher, report = ensure_managed_mcp_runtime(
        str(tmp_path),
        probe_func=lambda *_args, **_kwargs: {"ok": True},
    )

    assert launcher.command == str(launcher_path)
    assert report["status"] == "ok"


def test_ensure_managed_runtime_rebuilds_when_local_source_fingerprint_changes(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DOTSCOPE_MCP_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setattr(
        "dotscope.storage.mcp_runtime.resolve_managed_package_details",
        lambda: ("dotscope[mcp] @ file:///repo", "local-source", "new-fingerprint"),
    )

    python_path = managed_runtime_python_path(runtime_root)
    launcher_path = managed_runtime_launcher_path(runtime_root)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    launcher_path.write_text("", encoding="utf-8")

    state = ManagedRuntimeState(
        dotscope_version=__version__,
        runtime_root=str(runtime_root),
        python_executable=str(python_path),
        launcher_path=str(launcher_path),
        package_spec="dotscope[mcp] @ file:///repo",
        package_source="local-source",
        installed_at="2026-04-22T00:00:00+00:00",
        source_fingerprint="old-fingerprint",
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "install.json").write_text(json.dumps(state.__dict__), encoding="utf-8")

    rebuilds: list[Path] = []

    def fake_rebuild(root: Path) -> None:
        rebuilds.append(root)
        fresh_python = managed_runtime_python_path(root)
        fresh_launcher = managed_runtime_launcher_path(root)
        fresh_python.parent.mkdir(parents=True, exist_ok=True)
        fresh_python.write_text("", encoding="utf-8")
        fresh_launcher.write_text("", encoding="utf-8")

    monkeypatch.setattr("dotscope.storage.mcp_runtime._rebuild_managed_runtime", fake_rebuild)
    monkeypatch.setattr("dotscope.storage.mcp_runtime._install_runtime_package", lambda *_args, **_kwargs: None)

    launcher, report = ensure_managed_mcp_runtime(
        str(tmp_path),
        probe_func=lambda *_args, **_kwargs: {"ok": True},
    )

    assert launcher.command == str(launcher_path)
    assert rebuilds == [runtime_root]
    assert report["source_fingerprint"] == "new-fingerprint"


def test_diagnose_managed_runtime_reports_stale(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DOTSCOPE_MCP_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setattr(
        "dotscope.storage.mcp_runtime.resolve_managed_package_details",
        lambda: ("dotscope[mcp]==2.0.0", "published", "fingerprint-456"),
    )

    python_path = managed_runtime_python_path(runtime_root)
    launcher_path = managed_runtime_launcher_path(runtime_root)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    launcher_path.write_text("", encoding="utf-8")
    state = ManagedRuntimeState(
        dotscope_version=__version__,
        runtime_root=str(runtime_root),
        python_executable=str(python_path),
        launcher_path=str(launcher_path),
        package_spec="dotscope[mcp]==1.2.3",
        package_source="published",
        installed_at="2026-04-22T00:00:00+00:00",
        source_fingerprint="fingerprint-123",
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "install.json").write_text(json.dumps(state.__dict__), encoding="utf-8")

    report = diagnose_managed_mcp_runtime(
        str(tmp_path),
        probe_func=lambda *_args, **_kwargs: {"ok": True},
    )

    assert report["status"] == "stale"


def test_managed_runtime_lock_path_is_sibling_of_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime" / "1.2.3"
    monkeypatch.setenv("DOTSCOPE_MCP_RUNTIME_ROOT", str(runtime_root))

    lock_path = managed_runtime_lock_path()

    assert lock_path.parent == runtime_root.parent
    assert runtime_root not in lock_path.parents
