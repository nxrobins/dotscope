"""Tests for MCP launcher selection and config repair."""

from __future__ import annotations

import json

import pytest

from dotscope.storage.mcp_config import (
    McpBootContractError,
    McpLaunchSpec,
    _write_codex_toml,
    _write_cursor_config,
    _write_json_config,
    collect_mcp_launch_diagnostics,
    configure_mcp,
)


@pytest.fixture
def launch_spec():
    return McpLaunchSpec(
        command="/abs/path/dotscope-mcp",
        args=(),
        source="test",
    )


class TestWriteJsonConfig:
    def test_creates_new_file_with_entry(self, tmp_path):
        path = str(tmp_path / "config.json")
        entry = {"command": "/abs/path/dotscope-mcp", "args": ["--root", str(tmp_path)]}

        assert _write_json_config(path, "mcpServers", entry)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["mcpServers"]["dotscope"] == entry

    def test_merges_into_existing_config(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"mcpServers": {"other": {"command": "other"}}}, handle)

        entry = {"command": "/abs/path/dotscope-mcp", "args": ["--root", str(tmp_path)]}
        assert _write_json_config(path, "mcpServers", entry)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        assert "other" in data["mcpServers"]
        assert data["mcpServers"]["dotscope"] == entry

    def test_repairs_stale_entry(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"mcpServers": {"dotscope": {"command": "dotscope-mcp"}}}, handle)

        entry = {"command": "/abs/path/dotscope-mcp", "args": ["--root", str(tmp_path)]}
        assert _write_json_config(path, "mcpServers", entry)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["mcpServers"]["dotscope"] == entry

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{broken", encoding="utf-8")

        with pytest.raises(ValueError):
            _write_json_config(str(path), "mcpServers", {"command": "x"})


class TestCursorConfig:
    def test_uses_mcpservers_wrapper(self, tmp_path):
        path = str(tmp_path / ".cursor" / "mcp.json")
        entry = {"command": "/abs/path/dotscope-mcp", "args": ["--root", str(tmp_path)]}

        assert _write_cursor_config(path, entry)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        assert "mcpServers" in data
        assert data["mcpServers"]["dotscope"] == entry

    def test_migrates_legacy_flat_structure(self, tmp_path):
        path = tmp_path / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"other": {"command": "other-cmd"}}),
            encoding="utf-8",
        )

        entry = {"command": "/abs/path/dotscope-mcp", "args": ["--root", str(tmp_path)]}
        assert _write_cursor_config(str(path), entry)

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        assert "mcpServers" in data
        assert data["mcpServers"]["other"]["command"] == "other-cmd"
        assert data["mcpServers"]["dotscope"] == entry

    def test_idempotent_when_entry_matches(self, tmp_path):
        path = str(tmp_path / ".cursor" / "mcp.json")
        entry = {"command": "/abs/path/dotscope-mcp", "args": ["--root", str(tmp_path)]}
        _write_cursor_config(path, entry)

        assert not _write_cursor_config(path, entry)


class TestCodexToml:
    def test_creates_new_toml_with_args(self, tmp_path, launch_spec):
        path = str(tmp_path / ".codex" / "config.toml")

        assert _write_codex_toml(path, launch_spec, str(tmp_path))

        content = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "[mcp_servers.dotscope]" in content
        assert 'command = "/abs/path/dotscope-mcp"' in content
        assert '"--root"' in content

    def test_updates_existing_section(self, tmp_path, launch_spec):
        path = tmp_path / ".codex" / "config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            "[mcp_servers.dotscope]\ncommand = \"dotscope-mcp\"\n\n[other]\nkey = \"value\"\n",
            encoding="utf-8",
        )

        assert _write_codex_toml(str(path), launch_spec, str(tmp_path))

        content = path.read_text(encoding="utf-8")
        assert 'command = "/abs/path/dotscope-mcp"' in content
        assert '[other]\nkey = "value"' in content

    def test_idempotent_when_section_matches(self, tmp_path, launch_spec):
        path = str(tmp_path / ".codex" / "config.toml")
        _write_codex_toml(path, launch_spec, str(tmp_path))

        assert not _write_codex_toml(path, launch_spec, str(tmp_path))


class TestLauncherDiagnostics:
    def test_selects_first_working_candidate(self, monkeypatch, tmp_path):
        candidate_a = McpLaunchSpec(command="/a", args=(), source="a")
        candidate_b = McpLaunchSpec(command="/b", args=(), source="b")

        monkeypatch.setattr(
            "dotscope.storage.mcp_config._iter_launch_candidates",
            lambda: [candidate_a, candidate_b],
        )

        def fake_probe(candidate, _repo_root):
            if candidate.command == "/a":
                return {"ok": False, "error": "boom"}
            return {"ok": True, "tool_count": 14, "tools": ["resolve_scope"]}

        monkeypatch.setattr("dotscope.storage.mcp_config.probe_mcp_launch", fake_probe)

        selected, diagnostics = collect_mcp_launch_diagnostics(str(tmp_path))

        assert selected == candidate_b
        assert diagnostics[0]["ok"] is False
        assert diagnostics[1]["ok"] is True


class TestConfigureMcp:
    def test_preserves_launcher_args_returned_by_runtime(self, monkeypatch, tmp_path):
        repo_root = str(tmp_path)
        launch_spec = McpLaunchSpec(
            command="/abs/path/python",
            args=("-m", "dotscope.mcp"),
            source="managed-runtime",
        )

        monkeypatch.setattr(
            "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
            lambda _repo_root, probe_func, force_rebuild=False: (
                launch_spec,
                {
                    "status": "ok",
                    "action": "reused",
                    "launcher_path": launch_spec.command,
                    "runtime_root": str(tmp_path / "runtime"),
                    "probe": {"ok": True, "tool_count": 14, "tools": ["resolve_scope"]},
                    "timings_ms": {"total": 5},
                },
            ),
        )
        monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: "")
        monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")

        configure_mcp(repo_root)

        with open(tmp_path / ".mcp.json", encoding="utf-8") as handle:
            claude_code = json.load(handle)
        assert claude_code["mcpServers"]["dotscope"]["command"] == "/abs/path/python"
        assert claude_code["mcpServers"]["dotscope"]["args"] == ["-m", "dotscope.mcp", "--root", repo_root]

        codex = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert 'command = "/abs/path/python"' in codex
        assert '"-m"' in codex
        assert '"dotscope.mcp"' in codex

    def test_writes_absolute_launcher_everywhere(self, monkeypatch, tmp_path, launch_spec):
        repo_root = str(tmp_path)
        desktop = tmp_path / "global" / "claude_desktop_config.json"
        windsurf = tmp_path / "global" / "windsurf.json"

        monkeypatch.setattr(
            "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
            lambda _repo_root, probe_func, force_rebuild=False: (
                launch_spec,
                {
                    "status": "ok",
                    "action": "reused",
                    "launcher_path": launch_spec.command,
                    "runtime_root": str(tmp_path / "runtime"),
                    "probe": {"ok": True, "tool_count": 14, "tools": ["resolve_scope"]},
                    "timings_ms": {"total": 5},
                },
            ),
        )
        monkeypatch.setattr(
            "dotscope.storage.mcp_config._claude_desktop_config_path",
            lambda: str(desktop),
        )
        monkeypatch.setattr(
            "dotscope.storage.mcp_config._windsurf_config_path",
            lambda: str(windsurf),
        )

        configured = configure_mcp(repo_root)

        assert "Claude Code (.mcp.json)" in configured
        assert "Cursor" in configured
        assert "Codex CLI" in configured

        with open(tmp_path / ".mcp.json", encoding="utf-8") as handle:
            claude_code = json.load(handle)
        assert claude_code["mcpServers"]["dotscope"]["command"] == "/abs/path/dotscope-mcp"
        assert claude_code["mcpServers"]["dotscope"]["args"] == ["--root", repo_root]

        with open(tmp_path / ".cursor" / "mcp.json", encoding="utf-8") as handle:
            cursor = json.load(handle)
        assert cursor["mcpServers"]["dotscope"]["command"] == "/abs/path/dotscope-mcp"

        codex = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert 'command = "/abs/path/dotscope-mcp"' in codex
        assert json.dumps(repo_root) in codex

    def test_quiet_suppresses_manual_instructions(self, monkeypatch, tmp_path, launch_spec, capsys):
        repo_root = str(tmp_path)

        monkeypatch.setattr(
            "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
            lambda _repo_root, probe_func, force_rebuild=False: (
                launch_spec,
                {
                    "status": "ok",
                    "action": "reused",
                    "launcher_path": launch_spec.command,
                    "runtime_root": str(tmp_path / "runtime"),
                    "probe": {"ok": True, "tool_count": 14, "tools": ["resolve_scope"]},
                    "timings_ms": {"total": 5},
                },
            ),
        )
        monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: "")
        monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")

        configure_mcp(repo_root, quiet=True)

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_quiet_suppresses_config_write_errors(self, monkeypatch, tmp_path, launch_spec, capsys):
        repo_root = str(tmp_path)

        monkeypatch.setattr(
            "dotscope.storage.mcp_config.ensure_managed_mcp_runtime",
            lambda _repo_root, probe_func, force_rebuild=False: (
                launch_spec,
                {
                    "status": "ok",
                    "action": "reused",
                    "launcher_path": launch_spec.command,
                    "runtime_root": str(tmp_path / "runtime"),
                    "probe": {"ok": True, "tool_count": 14, "tools": ["resolve_scope"]},
                    "timings_ms": {"total": 5},
                },
            ),
        )
        monkeypatch.setattr(
            "dotscope.storage.mcp_config._write_json_config",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr("dotscope.storage.mcp_config._windsurf_config_path", lambda: "")
        monkeypatch.setattr("dotscope.storage.mcp_config._claude_desktop_config_path", lambda: "")

        with pytest.raises(McpBootContractError):
            configure_mcp(repo_root, quiet=True)

        captured = capsys.readouterr()
        assert captured.err == ""
