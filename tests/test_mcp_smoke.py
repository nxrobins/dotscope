"""Smoke tests for real MCP launcher probes when one is available."""

from dotscope.storage.mcp_config import collect_mcp_launch_diagnostics


def test_real_launcher_probe_when_available(tmp_project):
    launcher, diagnostics = collect_mcp_launch_diagnostics(str(tmp_project))
    if launcher is None:
        reasons = ", ".join(item.get("error", "unknown") for item in diagnostics) or "no candidates"
        import pytest

        pytest.skip(f"No working MCP launcher in this test environment: {reasons}")

    passing = next(item for item in diagnostics if item.get("ok"))
    assert passing["tool_count"] > 0
    assert "resolve_scope" in passing["tools"] or "list_scopes" in passing["tools"]
