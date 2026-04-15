"""Tests for the Dotscope Pro bridge layer.

The Pro backend is never contacted — every HTTP boundary is mocked with
``unittest.mock.patch``. Tests verify three states (connected+healthy,
connected+unhealthy/timeout, not configured), retry/backoff behavior, the
fail-silent guarantee on MCP/CLI integration points, and the critical
constraint that ``_cache.py`` performs zero filesystem I/O.
"""

import io
import json
import os
import socket
import sys
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import dotscope.pro as pro_pkg
from dotscope.pro import ProProvider, get_provider
from dotscope.pro._anonymize import anonymize_graph
from dotscope.pro._cache import cache_clear, cache_get, cache_set
from dotscope.pro.models import (
    Directive,
    FailureDensity,
    GlobalBaseline,
    StructuralAnalog,
    StructuralReport,
)
from dotscope.pro.remote import RemoteProProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    """Minimal stand-in for urllib.request.urlopen context manager."""

    def __init__(self, body):
        self._body = (
            body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


@pytest.fixture(autouse=True)
def _isolate_pro_env(tmp_path, monkeypatch):
    """Remove any real Pro env / credentials and isolate HOME to tmp_path."""
    monkeypatch.delenv("DOTSCOPE_PRO_URL", raising=False)
    monkeypatch.delenv("DOTSCOPE_PRO_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    # pathlib.Path.home() consults HOME on POSIX; on Windows it uses USERPROFILE
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cache_clear()
    yield
    cache_clear()


@pytest.fixture
def fake_graph():
    """Construct a small graph object exposing only the attributes we need."""
    nodes = {}
    for path in ("src/a.py", "src/b.py", "src/c.py"):
        nodes[path] = SimpleNamespace(
            path=path, imports=[], imported_by=[], loc=10
        )
    # a imports b, b imports c
    nodes["src/a.py"].imports = ["src/b.py"]
    nodes["src/b.py"].imports = ["src/c.py"]
    nodes["src/b.py"].imported_by = ["src/a.py"]
    nodes["src/c.py"].imported_by = ["src/b.py"]
    return SimpleNamespace(files=nodes)


# ---------------------------------------------------------------------------
# 1-4: get_provider() discovery
# ---------------------------------------------------------------------------


def test_get_provider_no_config():
    """No env vars and no credentials file → get_provider returns None."""
    assert get_provider() is None


def test_get_provider_env_wins(monkeypatch):
    """Env vars produce a RemoteProProvider with matching URL/token."""
    monkeypatch.setenv("DOTSCOPE_PRO_URL", "https://pro.example.com")
    monkeypatch.setenv("DOTSCOPE_PRO_TOKEN", "t0ken")
    p = get_provider()
    assert isinstance(p, RemoteProProvider)
    assert p._base_url == "https://pro.example.com"
    assert p._token == "t0ken"


def test_get_provider_credentials_file(tmp_path):
    """~/.dotscope/credentials JSON produces a RemoteProProvider."""
    cred_dir = tmp_path / ".dotscope"
    cred_dir.mkdir()
    (cred_dir / "credentials").write_text(
        json.dumps({"pro_url": "https://x", "token": "y"})
    )
    p = get_provider()
    assert isinstance(p, RemoteProProvider)
    assert p._base_url == "https://x"
    assert p._token == "y"


def test_get_provider_malformed_credentials(tmp_path):
    """Invalid JSON in credentials file → None (no exception bubbles)."""
    cred_dir = tmp_path / ".dotscope"
    cred_dir.mkdir()
    (cred_dir / "credentials").write_text("not-json{{")
    assert get_provider() is None


def test_get_provider_env_takes_precedence(tmp_path, monkeypatch):
    """When both env and file are present, env wins."""
    cred_dir = tmp_path / ".dotscope"
    cred_dir.mkdir()
    (cred_dir / "credentials").write_text(
        json.dumps({"pro_url": "https://file", "token": "ftok"})
    )
    monkeypatch.setenv("DOTSCOPE_PRO_URL", "https://env")
    monkeypatch.setenv("DOTSCOPE_PRO_TOKEN", "etok")
    p = get_provider()
    assert p._base_url == "https://env"
    assert p._token == "etok"


# ---------------------------------------------------------------------------
# 5-8: RemoteProProvider transport
# ---------------------------------------------------------------------------


def test_remote_post_timeout_returns_default():
    """Timeout (even after retries) yields a defaulted StructuralReport."""
    p = RemoteProProvider("http://x", "t")
    with mock.patch("dotscope.pro.remote.urllib.request.urlopen",
                    side_effect=TimeoutError("slow")):
        with mock.patch("dotscope.pro.remote.time.sleep"):
            result = p.compare_topology({"node_count": 0})
    assert isinstance(result, StructuralReport)
    assert result.analog_count == 0
    assert result.analogs == []


def test_remote_post_http_4xx_returns_default():
    """HTTP 4xx is fatal (no retry) and still yields defaulted result."""
    p = RemoteProProvider("http://x", "t")
    err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, io.BytesIO(b""))
    with mock.patch("dotscope.pro.remote.urllib.request.urlopen", side_effect=err) as m:
        with mock.patch("dotscope.pro.remote.time.sleep") as sleep_mock:
            result = p.compare_topology({})
    assert isinstance(result, StructuralReport)
    assert m.call_count == 1  # no retries on 4xx
    assert sleep_mock.call_count == 0


def test_remote_compare_success():
    """Happy path: parsed fields round-trip correctly."""
    payload = {
        "analog_count": 2,
        "analogs": [
            {
                "repo_domain": "compiler",
                "similarity_score": 0.87,
                "node_count": 100,
                "edge_count": 200,
                "insight": "Similar fan-in distribution",
            }
        ],
        "anomalies": ["unusual cycle density"],
        "directives": [
            {
                "directive_type": "decouple_warning",
                "target": "node_7",
                "reasoning": "crosses boundary",
                "severity": "warning",
                "confidence": 0.9,
            }
        ],
    }
    p = RemoteProProvider("http://x", "t")
    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen",
        return_value=_FakeResp(payload),
    ):
        result = p.compare_topology({"node_count": 10})
    assert isinstance(result, StructuralReport)
    assert result.analog_count == 2
    assert result.analogs[0].repo_domain == "compiler"
    assert result.directives[0].severity == "warning"


def test_is_healthy_ok():
    p = RemoteProProvider("http://x", "t")
    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen",
        return_value=_FakeResp({"status": "ok"}),
    ):
        assert p.is_healthy() is True


def test_is_healthy_unreachable():
    p = RemoteProProvider("http://x", "t")
    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen",
        side_effect=socket.timeout("too slow"),
    ):
        assert p.is_healthy() is False


# ---------------------------------------------------------------------------
# 9-10: Cache
# ---------------------------------------------------------------------------


def test_cache_ttl_expiry(monkeypatch):
    """Values older than 5 min are evicted on next get()."""
    fake_now = [1000.0]
    monkeypatch.setattr("dotscope.pro._cache.time.time", lambda: fake_now[0])

    cache_set("k", "v")
    assert cache_get("k") == "v"
    fake_now[0] += 100  # still within TTL
    assert cache_get("k") == "v"
    fake_now[0] += 300  # past 5-minute TTL
    assert cache_get("k") is None


def test_cache_no_disk_writes():
    """_cache.py source must contain zero filesystem operations.

    We parse the module AST and scan only executable statements, so the list
    of forbidden operations in the module docstring doesn't false-trigger.
    """
    import ast
    import dotscope.pro._cache as cache_mod

    tree = ast.parse(Path(cache_mod.__file__).read_text())

    forbidden_names = {"open", "makedirs", "mkdir", "fsync", "rename", "unlink"}
    forbidden_attrs = {"dump", "dumps_to_file", "write", "writelines"}  # json.dump, f.write, etc.
    forbidden_modules = {"pickle", "shelve", "pathlib", "shutil", "io"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules, (
                    f"_cache.py must not import {alias.name!r}"
                )
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden_modules, (
                f"_cache.py must not import from {node.module!r}"
            )
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                assert fn.id not in forbidden_names, (
                    f"_cache.py must not call {fn.id}()"
                )
            if isinstance(fn, ast.Attribute):
                assert fn.attr not in forbidden_attrs, (
                    f"_cache.py must not call .{fn.attr}()"
                )


# ---------------------------------------------------------------------------
# 11-12: Anonymizer
# ---------------------------------------------------------------------------


def test_anonymize_graph_strips_paths(fake_graph):
    """No original path strings may appear anywhere in the anonymized output."""
    out = anonymize_graph(fake_graph)
    serialized = json.dumps(out)
    assert "src/a.py" not in serialized
    assert "src/b.py" not in serialized
    assert "src/c.py" not in serialized
    assert out["node_count"] == 3
    assert len(out["in_degrees"]) == 3
    assert len(out["out_degrees"]) == 3
    # All edge endpoints are ints in [0, 3)
    for src, dst in out["edges"]:
        assert isinstance(src, int) and isinstance(dst, int)
        assert 0 <= src < 3 and 0 <= dst < 3


def test_anonymize_graph_shuffles_ids(fake_graph):
    """Running anonymize twice should (with overwhelming probability) yield
    different ID assignments — the degree *multisets* remain identical but
    the degree vectors (ordered by node ID) differ."""
    outs = [anonymize_graph(fake_graph) for _ in range(10)]
    # Sorted degree distributions are invariant.
    sorted_in = [tuple(sorted(o["in_degrees"])) for o in outs]
    assert len(set(sorted_in)) == 1
    # Ordered degree vectors should differ at least once across 10 runs.
    ordered = {tuple(o["in_degrees"]) for o in outs}
    assert len(ordered) > 1


def test_anonymize_empty_graph():
    """Empty graph → valid empty payload (no crash)."""
    out = anonymize_graph(SimpleNamespace(files={}))
    assert out == {
        "node_count": 0,
        "edges": [],
        "in_degrees": [],
        "out_degrees": [],
        "loc_per_node": [],
    }


# ---------------------------------------------------------------------------
# 13-14: MCP resolve_scope integration
# ---------------------------------------------------------------------------


def _make_resolve_state(gravity_score=0, extra_meta=None):
    meta = {"gravity_score": gravity_score}
    if extra_meta:
        meta.update(extra_meta)
    return {
        "data": {"action_hints": [], "files": []},
        "metadata": meta,
        "raw_output": "",
    }


def _run_resolve_with_state(state):
    """Execute the gravity + Pro enrichment logic in isolation.

    We don't spin up the full MCP pipeline — we replicate the minimum shape
    needed to exercise the action_hints block in core.py.
    """
    import json as _json
    import dotscope.mcp.core as core_mod

    fake_mcp = mock.MagicMock()
    captured = {}

    def record_tool(*a, **kw):
        def wrap(fn):
            captured[fn.__name__] = fn
            return fn
        return wrap

    fake_mcp.tool = record_tool

    # Register the tools against our fake MCP so we can grab resolve_scope.
    with mock.patch(
        "dotscope.mcp.core.get_standard_resolve_pipeline"
    ) as pipe_factory:
        pipe = mock.MagicMock()
        pipe.execute.return_value = state
        pipe_factory.return_value = pipe
        core_mod.register_core_tools(fake_mcp)
        result_json = captured["resolve_scope"](scope="dummy", root="/tmp")
    return _json.loads(result_json)


def test_resolve_scope_no_pro_unchanged():
    """With get_provider returning None, MCP output is unchanged from baseline."""
    state = _make_resolve_state(gravity_score=30)
    with mock.patch("dotscope.pro.get_provider", return_value=None):
        result = _run_resolve_with_state(state)
    hints = result["action_hints"]
    assert any("[DOTSCOPE_GRAVITY_NOTE]" in h for h in hints)
    assert not any("[DOTSCOPE_PRO_INSIGHT]" in h for h in hints)


def test_resolve_scope_with_pro_adds_one_hint():
    """Pro returning critical failure density adds exactly one extra hint."""
    state = _make_resolve_state(
        gravity_score=30, extra_meta={"loc": 250, "in_degree": 12}
    )
    fake_pro = mock.MagicMock()
    fake_pro.get_failure_density.return_value = FailureDensity(
        density=0.41,
        severity="critical",
        matched_repos=87,
        explanation="large hub under concurrent edits",
    )
    with mock.patch("dotscope.pro.get_provider", return_value=fake_pro):
        result = _run_resolve_with_state(state)
    hints = result["action_hints"]
    pro_hints = [h for h in hints if h.startswith("[DOTSCOPE_PRO_INSIGHT]")]
    assert len(pro_hints) == 1
    assert "41.0%" in pro_hints[0]
    assert "87" in pro_hints[0]


def test_resolve_scope_pro_gravity_too_low_no_hint():
    """Low gravity (<=10) → Pro is not even consulted."""
    state = _make_resolve_state(gravity_score=5)
    fake_pro = mock.MagicMock()
    fake_pro.get_failure_density.return_value = FailureDensity(
        density=0.9, severity="critical", matched_repos=1, explanation=""
    )
    with mock.patch("dotscope.pro.get_provider", return_value=fake_pro):
        result = _run_resolve_with_state(state)
    assert fake_pro.get_failure_density.call_count == 0
    hints = result["action_hints"]
    assert not any("DOTSCOPE_PRO_INSIGHT" in h for h in hints)


# ---------------------------------------------------------------------------
# 15-16: CLI fail-silent / status
# ---------------------------------------------------------------------------


def test_cmd_pro_status_no_config(capsys):
    """`dotscope pro status` with nothing configured → connection help."""
    from dotscope.cli.pro import _cmd_pro

    _cmd_pro(SimpleNamespace(pro_action="status"))
    out = capsys.readouterr().out
    assert "not connected" in out
    assert "dotscope pro login" in out


def test_maybe_pro_compare_silent_when_not_configured(capsys, tmp_path):
    """_maybe_pro_compare prints nothing when Pro is not configured."""
    from dotscope.cli.ingest import _maybe_pro_compare

    _maybe_pro_compare(str(tmp_path))
    out = capsys.readouterr().out
    assert out == ""


def test_maybe_pro_density_silent_when_not_configured(capsys):
    """_maybe_pro_density prints nothing when Pro is not configured."""
    from dotscope.cli.ingest import _maybe_pro_density

    _maybe_pro_density(None)
    out = capsys.readouterr().out
    assert out == ""


# ---------------------------------------------------------------------------
# 17-20: Retry / backoff
# ---------------------------------------------------------------------------


def test_remote_retries_on_transient():
    """Transient TimeoutError twice, then success — exactly 3 urlopen calls."""
    p = RemoteProProvider("http://x", "t")
    success = _FakeResp({"analog_count": 0, "analogs": [], "anomalies": [],
                          "directives": []})

    calls = {"n": 0}

    def side_effect(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("slow")
        return success

    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen", side_effect=side_effect
    ) as m:
        with mock.patch("dotscope.pro.remote.time.sleep"):
            result = p.compare_topology({"node_count": 0})

    assert m.call_count == 3
    assert isinstance(result, StructuralReport)


def test_remote_no_retry_on_4xx():
    """HTTP 4xx must be fatal — exactly one call, default result."""
    p = RemoteProProvider("http://x", "t")
    err = urllib.error.HTTPError("http://x", 403, "Forbidden", {}, io.BytesIO(b""))
    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen", side_effect=err
    ) as m:
        with mock.patch("dotscope.pro.remote.time.sleep") as sleep_mock:
            result = p.get_global_npmi_baseline()
    assert m.call_count == 1
    assert sleep_mock.call_count == 0
    assert isinstance(result, GlobalBaseline)
    assert result.repo_count == 0


def test_remote_gives_up_after_max_attempts():
    """Exactly 3 attempts then defaulted result; 2 backoff sleeps in between."""
    p = RemoteProProvider("http://x", "t")
    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen",
        side_effect=TimeoutError("nope"),
    ) as m:
        with mock.patch("dotscope.pro.remote.time.sleep") as sleep_mock:
            result = p.compare_topology({})
    assert m.call_count == 3
    assert sleep_mock.call_count == 2
    assert isinstance(result, StructuralReport)


def test_health_check_no_retry():
    """is_healthy makes exactly one call regardless of transient errors."""
    p = RemoteProProvider("http://x", "t")
    with mock.patch(
        "dotscope.pro.remote.urllib.request.urlopen",
        side_effect=TimeoutError("slow"),
    ) as m:
        with mock.patch("dotscope.pro.remote.time.sleep") as sleep_mock:
            assert p.is_healthy() is False
    assert m.call_count == 1
    assert sleep_mock.call_count == 0


# ---------------------------------------------------------------------------
# 21-25: Login / logout
# ---------------------------------------------------------------------------


def test_login_noninteractive_healthy(tmp_path, monkeypatch, capsys):
    """--url --token with a healthy backend writes credentials at 0o600."""
    from dotscope.cli.pro import _cmd_pro

    with mock.patch(
        "dotscope.pro.remote.RemoteProProvider.is_healthy", return_value=True
    ):
        _cmd_pro(SimpleNamespace(
            pro_action="login", url="https://pro.example.com", token="abc"
        ))

    cred = tmp_path / ".dotscope" / "credentials"
    assert cred.exists()
    data = json.loads(cred.read_text())
    assert data == {"pro_url": "https://pro.example.com", "token": "abc"}
    if os.name == "posix":
        mode = cred.stat().st_mode & 0o777
        assert mode == 0o600
    out = capsys.readouterr().out
    assert "Saved to" in out


def test_login_interactive(tmp_path, monkeypatch, capsys):
    """Prompts are used when --url/--token are omitted."""
    from dotscope.cli.pro import _cmd_pro

    inputs = iter(["https://pro.example.com"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))
    monkeypatch.setattr("dotscope.cli.pro.getpass.getpass", lambda *_a, **_k: "secret")

    with mock.patch(
        "dotscope.pro.remote.RemoteProProvider.is_healthy", return_value=True
    ):
        _cmd_pro(SimpleNamespace(pro_action="login", url=None, token=None))

    data = json.loads((tmp_path / ".dotscope" / "credentials").read_text())
    assert data == {"pro_url": "https://pro.example.com", "token": "secret"}


def test_login_invalid_url_reprompts(tmp_path, monkeypatch, capsys):
    """Invalid URLs re-prompt up to 3 times before giving up."""
    from dotscope.cli.pro import _cmd_pro

    inputs = iter(["not-a-url", "also-bad", "nope-again"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))
    monkeypatch.setattr("dotscope.cli.pro.getpass.getpass", lambda *_a, **_k: "secret")

    with pytest.raises(SystemExit):
        _cmd_pro(SimpleNamespace(pro_action="login", url=None, token=None))

    assert not (tmp_path / ".dotscope" / "credentials").exists()


def test_login_unhealthy_prompts_save(tmp_path, monkeypatch, capsys):
    """When the backend is unreachable, user is asked before saving."""
    from dotscope.cli.pro import _cmd_pro

    # First run: decline to save.
    inputs = iter(["https://pro.example.com", "n"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))
    monkeypatch.setattr("dotscope.cli.pro.getpass.getpass", lambda *_a, **_k: "tok")
    with mock.patch(
        "dotscope.pro.remote.RemoteProProvider.is_healthy", return_value=False
    ):
        _cmd_pro(SimpleNamespace(pro_action="login", url=None, token=None))
    assert not (tmp_path / ".dotscope" / "credentials").exists()

    # Second run: accept to save.
    inputs2 = iter(["https://pro.example.com", "y"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs2))
    with mock.patch(
        "dotscope.pro.remote.RemoteProProvider.is_healthy", return_value=False
    ):
        _cmd_pro(SimpleNamespace(pro_action="login", url=None, token=None))
    assert (tmp_path / ".dotscope" / "credentials").exists()


def test_login_noninteractive_unhealthy_refuses(tmp_path, capsys):
    """CI-style non-interactive login must NOT silently save bad credentials."""
    from dotscope.cli.pro import _cmd_pro

    with mock.patch(
        "dotscope.pro.remote.RemoteProProvider.is_healthy", return_value=False
    ):
        with pytest.raises(SystemExit):
            _cmd_pro(SimpleNamespace(
                pro_action="login", url="https://dead.example.com", token="x"
            ))
    assert not (tmp_path / ".dotscope" / "credentials").exists()


def test_logout_removes_credentials(tmp_path, capsys):
    """logout unlinks the credentials file; idempotent on repeat."""
    from dotscope.cli.pro import _cmd_pro

    cred_dir = tmp_path / ".dotscope"
    cred_dir.mkdir()
    cred = cred_dir / "credentials"
    cred.write_text(json.dumps({"pro_url": "x", "token": "y"}))

    _cmd_pro(SimpleNamespace(pro_action="logout"))
    assert not cred.exists()
    out1 = capsys.readouterr().out
    assert "Removed" in out1

    # Idempotent.
    _cmd_pro(SimpleNamespace(pro_action="logout"))
    out2 = capsys.readouterr().out
    assert "Already logged out" in out2
