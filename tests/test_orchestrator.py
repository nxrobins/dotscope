"""Tests for `dotscope orchestrator`. The Claude Agent SDK is mocked
end-to-end via a fake `query()` and fake message types so the orchestrator
runs in CI without claude-agent-sdk installed."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from dotscope.orchestrator import (
    BaselineContaminationError,
    OrchestratorError,
    REGRESSION_CACHE_DIR,
    TurnTokenBuffer,
    TurnTokenRecord,
    assert_no_inherited_mcp_config,
    baseline_tool_inventory_check,
    build_sdk_options,
    regression_cache_key,
    run_arm,
    run_pair,
    stream_assistant_usage,
    verify_regression,
)
from dotscope.trial import TrialStore


# ---------------------------------------------------------------------------
# Test repo helpers (lifted from test_trial.py)
# ---------------------------------------------------------------------------

def _init_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True
    )
    (tmp_path / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Fake SDK
# ---------------------------------------------------------------------------

@dataclass
class FakeAssistantMessage:
    message_id: str
    usage: Dict[str, Any]
    text: str = ""


class FakeQuery:
    """Async-iterable fake of claude_agent_sdk.query(). Returns a canned
    sequence of messages and records the last options it was called with."""

    def __init__(self, scripts: Dict[str, List[FakeAssistantMessage]]):
        # scripts: prompt -> messages to yield
        self._scripts = scripts
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, *, prompt: str, options: Dict[str, Any]):
        self.calls.append({"prompt": prompt, "options": options})
        messages = self._scripts.get(prompt, [])

        async def _gen():
            for m in messages:
                yield m

        return _gen()


def _is_assistant(m: Any) -> bool:
    return isinstance(m, FakeAssistantMessage)


def _is_system(_m: Any) -> bool:
    return False


def _extract_id_and_usage(m: Any) -> Tuple[Optional[str], Dict[str, Any]]:
    return m.message_id, m.usage


def _extract_text(m: Any) -> str:
    return m.text


# ---------------------------------------------------------------------------
# TurnTokenBuffer
# ---------------------------------------------------------------------------

class TestTurnTokenBuffer:
    def test_empty_buffer(self):
        buf = TurnTokenBuffer()
        assert buf.records() == []
        assert buf.total_billed_input() == 0

    def test_records_per_message_id(self):
        buf = TurnTokenBuffer()
        buf.observe("m1", {"input_tokens": 100, "cache_creation_input_tokens": 10,
                            "cache_read_input_tokens": 5})
        buf.observe("m2", {"input_tokens": 200})
        records = sorted(buf.records(), key=lambda r: r.message_id)
        assert len(records) == 2
        assert records[0].billed_input_sum == 115
        assert records[1].billed_input_sum == 200
        assert buf.total_billed_input() == 315

    def test_latest_wins_on_same_message_id(self):
        buf = TurnTokenBuffer()
        buf.observe("m1", {"input_tokens": 100})
        buf.observe("m1", {"input_tokens": 150, "cache_read_input_tokens": 50})
        records = buf.records()
        assert len(records) == 1
        assert records[0].input_tokens == 150
        assert records[0].cache_read_input_tokens == 50
        assert records[0].billed_input_sum == 200

    def test_audit_log_written(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        buf = TurnTokenBuffer(audit_path=audit)
        buf.observe("m1", {"input_tokens": 100})
        buf.observe("m1", {"input_tokens": 150})
        lines = audit.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        last = json.loads(lines[-1])
        assert last["source"] == "superseded"
        assert last["previous"] == {
            "input_tokens": 100,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

    def test_empty_message_id_is_ignored(self):
        buf = TurnTokenBuffer()
        buf.observe("", {"input_tokens": 100})
        assert buf.records() == []


# ---------------------------------------------------------------------------
# assert_no_inherited_mcp_config
# ---------------------------------------------------------------------------

class TestContaminationFilesystemWalk:
    def test_clean_tree_passes(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        # Walk to filesystem root could find configs in the user's $HOME.
        # The test tmp_path is isolated; assert no findings inside the
        # subtree we control. The walk extends to $HOME so we relax the
        # invariant: assert that *worktree-internal* findings are empty.
        findings = assert_no_inherited_mcp_config(worktree, fail_loud=False)
        worktree_internal = [
            f for f in findings if Path(f.path).is_relative_to(tmp_path)
        ]
        assert worktree_internal == []

    def test_finds_mcp_json_in_worktree(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".mcp.json").write_text("{}", encoding="utf-8")
        findings = assert_no_inherited_mcp_config(worktree, fail_loud=False)
        local_findings = [
            f for f in findings if Path(f.path).is_relative_to(tmp_path)
        ]
        assert any(f.path.endswith(".mcp.json") for f in local_findings)

    def test_finds_claude_settings_in_ancestor(self, tmp_path):
        ancestor = tmp_path / "outer"
        worktree = ancestor / "inner" / "worktree"
        worktree.mkdir(parents=True)
        (ancestor / ".claude").mkdir()
        (ancestor / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        findings = assert_no_inherited_mcp_config(worktree, fail_loud=False)
        assert any("settings.json" in f.path for f in findings)

    def test_fail_loud_raises_on_finding(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".mcp.json").write_text("{}", encoding="utf-8")
        with pytest.raises(BaselineContaminationError):
            assert_no_inherited_mcp_config(worktree, fail_loud=True)


# ---------------------------------------------------------------------------
# build_sdk_options
# ---------------------------------------------------------------------------

class TestBuildSdkOptions:
    def test_dotscope_arm_includes_dotscope_mcp(self, tmp_path):
        spec = build_sdk_options("dotscope", tmp_path, "claude-opus-4-7")
        assert spec.mcp_servers == {
            "dotscope": {"type": "stdio", "command": "dotscope-mcp"}
        }
        assert spec.setting_sources == ["local"]
        assert spec.cwd == str(tmp_path.resolve())

    def test_baseline_arm_has_empty_mcp_servers(self, tmp_path):
        spec = build_sdk_options("baseline", tmp_path, "claude-opus-4-7")
        assert spec.mcp_servers == {}
        assert spec.setting_sources == ["local"]

    def test_unknown_arm_rejected(self, tmp_path):
        with pytest.raises(OrchestratorError):
            build_sdk_options("control", tmp_path, "claude-opus-4-7")

    def test_to_kwargs_shape(self, tmp_path):
        spec = build_sdk_options(
            "dotscope", tmp_path, "claude-opus-4-7", max_turns=5,
            system_prompt="hello",
        )
        kwargs = spec.to_kwargs()
        assert kwargs["mcp_servers"] == {
            "dotscope": {"type": "stdio", "command": "dotscope-mcp"}
        }
        assert kwargs["setting_sources"] == ["local"]
        assert kwargs["max_turns"] == 5
        assert kwargs["system_prompt"] == "hello"
        assert kwargs["model"] == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# regression_cache_key + verify_regression
# ---------------------------------------------------------------------------

class TestRegressionCacheKey:
    def test_deterministic(self):
        a = regression_cache_key("r/p", 1, "abc", "tests/test_a.py", "1.0")
        b = regression_cache_key("r/p", 1, "abc", "tests/test_a.py", "1.0")
        assert a == b

    def test_changes_on_cut_score_version(self):
        a = regression_cache_key("r/p", 1, "abc", "tests/test_a.py", "1.0")
        b = regression_cache_key("r/p", 1, "abc", "tests/test_a.py", "2.0")
        assert a != b


class TestVerifyRegression:
    def _run(
        self,
        tmp_path,
        *,
        runs_payload,
        git_calls=None,
    ):
        if git_calls is None:
            git_calls = []

        def fake_git(args, cwd):
            git_calls.append((tuple(args), cwd))
            return ""

        def fake_pytest(commands, cwd, runs):
            return runs_payload

        cache_dir = tmp_path / "cache"
        worktrees = tmp_path / "worktrees"
        worktrees.mkdir(parents=True, exist_ok=True)
        return verify_regression(
            repo="x/y", pr=1, parent_sha="abc",
            test_path="tests/test_a.py",
            worktree_root=worktrees, cut_score_version="1.0",
            cache_dir=cache_dir,
            git_runner=fake_git,
            pytest_runner=fake_pytest,
        ), git_calls, cache_dir

    def test_real_regression_when_runs_fail(self, tmp_path):
        status, _, _ = self._run(
            tmp_path,
            runs_payload=[
                {"run": 1, "passed": False},
                {"run": 2, "passed": False},
            ],
        )
        assert status.is_regression is True
        assert status.reason == "real_regression"
        assert status.cache_hit is False

    def test_not_a_regression_when_runs_pass(self, tmp_path):
        status, _, _ = self._run(
            tmp_path,
            runs_payload=[
                {"run": 1, "passed": True},
                {"run": 2, "passed": True},
            ],
        )
        assert status.is_regression is False
        assert status.reason == "not_a_regression"

    def test_flaky_on_parent(self, tmp_path):
        status, _, _ = self._run(
            tmp_path,
            runs_payload=[
                {"run": 1, "passed": True},
                {"run": 2, "passed": False},
            ],
        )
        assert status.is_regression is False
        assert status.reason == "flaky_on_parent"

    def test_cache_hit_skips_pytest(self, tmp_path):
        # First run populates cache.
        self._run(
            tmp_path,
            runs_payload=[
                {"run": 1, "passed": False},
                {"run": 2, "passed": False},
            ],
        )

        # Second call should hit cache; pytest_runner should not be invoked.
        invoked = {"count": 0}

        def fake_pytest(commands, cwd, runs):
            invoked["count"] += 1
            return []

        def fake_git(args, cwd):
            return ""

        cache_dir = tmp_path / "cache"
        worktrees = tmp_path / "worktrees"
        status = verify_regression(
            repo="x/y", pr=1, parent_sha="abc",
            test_path="tests/test_a.py",
            worktree_root=worktrees, cut_score_version="1.0",
            cache_dir=cache_dir,
            git_runner=fake_git,
            pytest_runner=fake_pytest,
        )
        assert status.cache_hit is True
        assert status.is_regression is True
        assert invoked["count"] == 0

    def test_corrupted_cache_entry_is_recomputed(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        key = regression_cache_key("x/y", 1, "abc", "tests/test_a.py", "1.0")
        (cache_dir / f"{key}.json").write_text("{bogus", encoding="utf-8")

        invoked = {"count": 0}

        def fake_pytest(commands, cwd, runs):
            invoked["count"] += 1
            return [{"run": 1, "passed": False}, {"run": 2, "passed": False}]

        def fake_git(args, cwd):
            return ""

        worktrees = tmp_path / "worktrees"
        worktrees.mkdir()
        status = verify_regression(
            repo="x/y", pr=1, parent_sha="abc",
            test_path="tests/test_a.py",
            worktree_root=worktrees, cut_score_version="1.0",
            cache_dir=cache_dir,
            git_runner=fake_git,
            pytest_runner=fake_pytest,
        )
        assert status.cache_hit is False
        assert invoked["count"] == 1
        assert status.is_regression is True


# ---------------------------------------------------------------------------
# run_arm with fake SDK
# ---------------------------------------------------------------------------

class TestRunArm:
    def test_records_one_event_per_message_id(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        store = TrialStore(str(repo))
        pair = store.create_pair(task="t", model="claude-opus-4-7", client="c")

        scripts = {
            "fix bug X": [
                FakeAssistantMessage("turn-1", {"input_tokens": 100,
                                                  "cache_creation_input_tokens": 0,
                                                  "cache_read_input_tokens": 0}),
                # Same message_id with corrected (latest) usage — buffer keeps latest
                FakeAssistantMessage("turn-1", {"input_tokens": 150,
                                                  "cache_creation_input_tokens": 0,
                                                  "cache_read_input_tokens": 50}),
                FakeAssistantMessage("turn-2", {"input_tokens": 200,
                                                  "cache_creation_input_tokens": 30,
                                                  "cache_read_input_tokens": 100}),
            ]
        }
        sdk = FakeQuery(scripts)

        result = asyncio.run(run_arm(
            store=store,
            pair_id=pair["pair_id"],
            arm="dotscope",
            worktree_path=Path(repo),
            model="claude-opus-4-7",
            prompt="fix bug X",
            sdk_query=sdk,
            is_assistant_message=_is_assistant,
            extract_message_id_and_usage=_extract_id_and_usage,
            validation_commands=[f"{sys.executable} -c \"pass\""],
            validation_runs=2,
            timeout_hours=0.1,
            contamination_stop_at=tmp_path,
        ))

        assert result.arm == "dotscope"
        assert result.public_valid is True
        assert result.turn_count == 2  # turn-1 deduped + turn-2

        events = store.load_events(result.trial_id)
        token_events = [e for e in events if e.get("type") == "token_usage"]
        assert len(token_events) == 2
        ids = sorted(e["turn_id"] for e in token_events)
        assert ids == ["turn-1", "turn-2"]
        # turn-1 latest: 150 + 0 + 50 = 200
        e1 = next(e for e in token_events if e["turn_id"] == "turn-1")
        assert e1["input_tokens"] == 200
        assert e1["cache_read_input_tokens"] == 50
        # turn-2: 200 + 30 + 100 = 330
        e2 = next(e for e in token_events if e["turn_id"] == "turn-2")
        assert e2["input_tokens"] == 330
        assert e2["cache_creation_input_tokens"] == 30

    def test_sdk_options_for_dotscope_arm_passed_through(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        store = TrialStore(str(repo))
        pair = store.create_pair(task="t", model="m", client="c")
        sdk = FakeQuery({"p": []})

        asyncio.run(run_arm(
            store=store,
            pair_id=pair["pair_id"],
            arm="dotscope",
            worktree_path=Path(repo),
            model="m",
            prompt="p",
            sdk_query=sdk,
            is_assistant_message=_is_assistant,
            extract_message_id_and_usage=_extract_id_and_usage,
            validation_commands=[],
            timeout_hours=0.1,
            contamination_stop_at=tmp_path,
        ))
        assert sdk.calls
        opts = sdk.calls[-1]["options"]
        assert opts["mcp_servers"] == {
            "dotscope": {"type": "stdio", "command": "dotscope-mcp"}
        }
        assert opts["setting_sources"] == ["local"]


# ---------------------------------------------------------------------------
# baseline_tool_inventory_check
# ---------------------------------------------------------------------------

class TestBaselineToolInventory:
    def test_passes_when_inventory_lacks_dotscope(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        scripts = {
            # The probe prompt is the constant INVENTORY_PROBE_PROMPT
            __import__("dotscope.orchestrator", fromlist=[
                "INVENTORY_PROBE_PROMPT"
            ]).INVENTORY_PROBE_PROMPT: [
                FakeAssistantMessage(
                    "msg-1", {"input_tokens": 10},
                    text='["Read", "Write", "Bash"]',
                ),
            ]
        }
        sdk = FakeQuery(scripts)

        result = asyncio.run(baseline_tool_inventory_check(
            sdk_query=sdk,
            worktree_path=worktree,
            model="claude-opus-4-7",
            is_assistant_message=_is_assistant,
            extract_text_content=_extract_text,
        ))
        assert result["leaked"] == []
        assert result["advertised"] == ["Read", "Write", "Bash"]

    def test_raises_when_dotscope_tool_advertised(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        scripts = {
            __import__("dotscope.orchestrator", fromlist=[
                "INVENTORY_PROBE_PROMPT"
            ]).INVENTORY_PROBE_PROMPT: [
                FakeAssistantMessage(
                    "msg-1", {"input_tokens": 10},
                    text='["Read", "dotscope_resolve_scope"]',
                ),
            ]
        }
        sdk = FakeQuery(scripts)

        with pytest.raises(BaselineContaminationError):
            asyncio.run(baseline_tool_inventory_check(
                sdk_query=sdk,
                worktree_path=worktree,
                model="claude-opus-4-7",
                is_assistant_message=_is_assistant,
                extract_text_content=_extract_text,
            ))


# ---------------------------------------------------------------------------
# run_pair end-to-end
# ---------------------------------------------------------------------------

class TestRunPair:
    def test_drives_both_arms_in_arm_order(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        store = TrialStore(str(repo))
        worktrees_root = tmp_path / "wtroots"
        worktrees_root.mkdir()

        # Both arms produce one assistant turn each.
        scripts = {
            "the prompt": [
                FakeAssistantMessage("msg-1", {"input_tokens": 100}),
            ]
        }
        # Inventory probe prompt for baseline.
        from dotscope.orchestrator import INVENTORY_PROBE_PROMPT
        scripts[INVENTORY_PROBE_PROMPT] = [
            FakeAssistantMessage("probe-msg", {"input_tokens": 5}, text='["Read"]'),
        ]
        sdk = FakeQuery(scripts)

        # Stub git runner: copy the source repo so both arms see identical HEAD.
        # Real `git worktree add` would produce the same HEAD by construction;
        # this mock approximates that property.
        import shutil
        git_calls: List[Tuple[Tuple[str, ...], str]] = []

        def fake_git(args, cwd):
            git_calls.append((tuple(args), cwd))
            if args[:2] == ["worktree", "add"]:
                target = Path(args[2])
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(repo, target)
            elif args[:2] == ["worktree", "remove"]:
                target = Path(args[-1])
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            return ""

        result = asyncio.run(run_pair(
            store=store,
            task="task-x",
            model="claude-opus-4-7",
            client="claude-agent-sdk",
            project="x/y",
            base_ref="HEAD",
            prompt="the prompt",
            worktrees_root=worktrees_root,
            sdk_query=sdk,
            is_assistant_message=_is_assistant,
            extract_message_id_and_usage=_extract_id_and_usage,
            extract_text_content=_extract_text,
            git_runner=fake_git,
            validation_commands=[f"{sys.executable} -c \"pass\""],
            validation_runs=2,
            timeout_hours=0.1,
            contamination_stop_at=tmp_path,
        ))

        assert result.arm_order in (["dotscope", "baseline"], ["baseline", "dotscope"])
        assert len(result.results) == 2
        assert all(r.public_valid for r in result.results)
        # public_valid combines all the harness's agreement+integrity checks
        # into one pass/fail. Both arms used token_fidelity=A and matching
        # accounting policy, so the pair should be public-valid.
        cmp = store.compare_pair(result.pair_id)
        assert result.public_valid is True, f"reasons: {cmp.get('reasons')}"
