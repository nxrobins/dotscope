"""Live trial orchestrator: spawns Claude Code per arm via the Claude Agent SDK,
captures provider-reported tokens with cache-aware accounting, runs the
harness CLI for bookkeeping, and applies pre-flight regression verification
plus baseline contamination defense.

Methodological constraint: this orchestrator is the operator-launched driver.
It calls the harness directly (not via subprocess CLI) because both live in
the same dotscope package. Each arm runs a fresh `claude_agent_sdk.query()`
in its own worktree with a per-arm `mcp_servers` configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from .storage.atomic import atomic_write_json, atomic_write_text
from .trial import TrialError, TrialStore, classify_validation, run_validations


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORCH_VERSION = "1.0"
DEFAULT_AUDIT_RETENTION_DAYS = 30
DEFAULT_AUDIT_DELETE_DAYS = 90
DEFAULT_MAX_AUDIT_BYTES = 100 * 1024 * 1024  # 100 MiB
MCP_CONFIG_FILENAMES = (
    ".mcp.json",
    ".claude.json",
    "claude_desktop_config.json",
)
CLAUDE_DIR_NAME = ".claude"
DOTSCOPE_TOOL_PREFIX = "dotscope"
CAPTURE_METHOD = "agent_sdk_stream_billed_input_sum"


class OrchestratorError(RuntimeError):
    """Raised when the orchestrator cannot continue safely."""


class BaselineContaminationError(OrchestratorError):
    """Raised when a baseline arm would or did encounter dotscope tools."""


# ---------------------------------------------------------------------------
# Per-turn token buffer
# ---------------------------------------------------------------------------

@dataclass
class TurnTokenRecord:
    message_id: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

    @property
    def billed_input_sum(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


class TurnTokenBuffer:
    """Buffers per-message_id usage with latest-wins semantics.

    Parallel tool calls produce multiple AssistantMessage events sharing one
    `message_id` with identical usage; retries or partial-then-corrected
    streams may emit different usage under the same id. This buffer keeps
    only the latest seen usage per id and flushes one record per id at
    end-of-arm. The harness rejects duplicate (trial_id, turn_id) so the
    flush ordering does not matter.
    """

    def __init__(self, audit_path: Optional[Path] = None):
        self._latest: Dict[str, Dict[str, int]] = {}
        self._audit_path = audit_path

    def observe(self, message_id: str, usage: Dict[str, Any]) -> None:
        if not message_id:
            return
        normalized = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "cache_creation_input_tokens": int(
                usage.get("cache_creation_input_tokens") or 0
            ),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        }
        prior = self._latest.get(message_id)
        self._latest[message_id] = normalized
        if self._audit_path:
            source = "superseded" if prior and prior != normalized else "raw"
            self._append_audit({
                "ts": datetime.now(timezone.utc).isoformat(),
                "message_id": message_id,
                "usage": normalized,
                "previous": prior,
                "source": source,
            })

    def records(self) -> List[TurnTokenRecord]:
        return [
            TurnTokenRecord(
                message_id=mid,
                input_tokens=u["input_tokens"],
                cache_creation_input_tokens=u["cache_creation_input_tokens"],
                cache_read_input_tokens=u["cache_read_input_tokens"],
            )
            for mid, u in self._latest.items()
        ]

    def total_billed_input(self) -> int:
        return sum(r.billed_input_sum for r in self.records())

    def _append_audit(self, payload: Dict[str, Any]) -> None:
        path = self._audit_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Contamination defense (Layer 3)
# ---------------------------------------------------------------------------

@dataclass
class ConfigFinding:
    path: str
    kind: str  # "file" | "dir"


def assert_no_inherited_mcp_config(
    worktree: str | os.PathLike[str],
    *,
    fail_loud: bool = True,
    stop_at_directory: Optional[str | os.PathLike[str]] = None,
) -> List[ConfigFinding]:
    """Walk from `worktree` up through every ancestor (to filesystem root, or
    to `stop_at_directory` inclusive) and flag any MCP/Claude config files.
    With `fail_loud=True` (baseline-arm contract) raises
    BaselineContaminationError on any finding. Returns the list of findings
    either way.

    `stop_at_directory` is a test/operator hook to bound the walk; production
    baseline arms should leave it unset so the walk hits filesystem root.
    """
    findings: List[ConfigFinding] = []
    start = Path(worktree).resolve()
    stop = Path(stop_at_directory).resolve() if stop_at_directory else None
    seen: set = set()
    current = start
    while True:
        if current in seen:
            break
        seen.add(current)
        for name in MCP_CONFIG_FILENAMES:
            candidate = current / name
            if candidate.exists():
                findings.append(ConfigFinding(path=str(candidate), kind="file"))
        claude_dir = current / CLAUDE_DIR_NAME
        if claude_dir.exists() and claude_dir.is_dir():
            settings = claude_dir / "settings.json"
            if settings.exists():
                findings.append(ConfigFinding(path=str(settings), kind="file"))
        if stop is not None and current == stop:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    if findings and fail_loud:
        paths = ", ".join(f.path for f in findings)
        raise BaselineContaminationError(
            f"MCP/Claude configs found in worktree ancestry: {paths}. "
            "setting_sources=['local'] should suppress these, but the baseline "
            "arm refuses to run if any are detected. Move or unset them and retry."
        )
    return findings


# ---------------------------------------------------------------------------
# SDK options builder
# ---------------------------------------------------------------------------

@dataclass
class SdkOptionSpec:
    """Plain-data spec for ClaudeAgentOptions kwargs.

    Kept as a dataclass so callers can introspect/test without importing
    claude_agent_sdk. `to_kwargs()` materializes the dict the SDK constructor
    expects.
    """

    arm: str
    cwd: str
    mcp_servers: Dict[str, Any]
    setting_sources: List[str]
    model: str
    permission_mode: str = "bypassPermissions"
    allowed_tools: Optional[List[str]] = None
    max_turns: Optional[int] = None
    system_prompt: Optional[str] = None

    def to_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "cwd": self.cwd,
            "mcp_servers": dict(self.mcp_servers),
            "setting_sources": list(self.setting_sources),
            "model": self.model,
            "permission_mode": self.permission_mode,
        }
        if self.allowed_tools is not None:
            kwargs["allowed_tools"] = list(self.allowed_tools)
        if self.max_turns is not None:
            kwargs["max_turns"] = self.max_turns
        if self.system_prompt is not None:
            kwargs["system_prompt"] = self.system_prompt
        return kwargs


def build_sdk_options(
    arm: str,
    worktree_path: str | os.PathLike[str],
    model: str,
    *,
    dotscope_mcp_command: str = "dotscope-mcp",
    permission_mode: str = "bypassPermissions",
    max_turns: Optional[int] = None,
    system_prompt: Optional[str] = None,
) -> SdkOptionSpec:
    """Construct per-arm SDK options.

    Dotscope arm: mcp_servers={"dotscope": {"type": "stdio",
    "command": dotscope_mcp_command}}.
    Baseline arm: mcp_servers={} (empty).
    Both arms force setting_sources=["local"] to suppress
    user-level (~/.claude/) and project-level (.mcp.json) MCP discovery.
    """
    if arm == "dotscope":
        mcp_servers: Dict[str, Any] = {
            "dotscope": {
                "type": "stdio",
                "command": dotscope_mcp_command,
            }
        }
    elif arm == "baseline":
        mcp_servers = {}
    else:
        raise OrchestratorError(f"unknown arm: {arm!r}")

    return SdkOptionSpec(
        arm=arm,
        cwd=str(Path(worktree_path).resolve()),
        mcp_servers=mcp_servers,
        setting_sources=["local"],
        model=model,
        permission_mode=permission_mode,
        max_turns=max_turns,
        system_prompt=system_prompt,
    )


# ---------------------------------------------------------------------------
# Pre-flight regression verifier
# ---------------------------------------------------------------------------

@dataclass
class RegressionStatus:
    is_regression: bool
    reason: str  # "real_regression" | "not_a_regression" | "flaky_on_parent" |
                 # "collection_error"
    cache_hit: bool = False
    runs: List[Dict[str, Any]] = field(default_factory=list)


REGRESSION_CACHE_DIR = Path(os.path.expanduser("~/.dotscope-trials/regression_cache"))


def regression_cache_key(
    repo: str,
    pr: int,
    parent_sha: str,
    test_path: str,
    cut_score_version: str,
) -> str:
    payload = f"{repo}|{pr}|{parent_sha}|{test_path}|{cut_score_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_regression_cache(key: str, cache_dir: Path) -> Optional[Dict[str, Any]]:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Corrupted cache entry — delete and re-verify
        try:
            path.unlink()
        except OSError:
            pass
        return None


def _store_regression_cache(
    key: str,
    payload: Dict[str, Any],
    cache_dir: Path,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cache_dir / f"{key}.json", payload)


def verify_regression(
    *,
    repo: str,
    pr: int,
    parent_sha: str,
    test_path: str,
    worktree_root: Path,
    cut_score_version: str,
    validation_runs: int = 2,
    cache_dir: Path = REGRESSION_CACHE_DIR,
    git_runner: Callable[[List[str], str], str] = None,
    pytest_runner: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> RegressionStatus:
    """Verify that running `pytest <test_path>` on `parent_sha` actually
    fails — i.e., the test is a real regression. Caches the result by
    (repo, pr, parent_sha, test_path, cut_score_version).

    `git_runner` and `pytest_runner` are dependency injection points for
    tests; default to subprocess-based implementations.
    """
    key = regression_cache_key(
        repo=repo, pr=pr, parent_sha=parent_sha,
        test_path=test_path, cut_score_version=cut_score_version,
    )
    cached = _load_regression_cache(key, cache_dir)
    if cached:
        return RegressionStatus(
            is_regression=cached["is_regression"],
            reason=cached["reason"],
            cache_hit=True,
            runs=cached.get("runs", []),
        )

    git_runner = git_runner or _default_git_runner
    pytest_runner = pytest_runner or _default_pytest_runner

    scratch = worktree_root / f"verify_{key[:12]}"
    if scratch.exists():
        # Tear down a stale scratch worktree from a prior crashed run
        git_runner(["worktree", "remove", "--force", str(scratch)], str(worktree_root))

    git_runner(["worktree", "add", str(scratch), parent_sha], str(worktree_root))
    try:
        runs = pytest_runner(
            commands=[f"pytest {test_path}"],
            cwd=str(scratch),
            runs=validation_runs,
        )
        status_label = classify_validation(runs)
        if status_label == "failure":
            payload = {
                "is_regression": True,
                "reason": "real_regression",
                "runs": runs,
            }
        elif status_label == "success":
            payload = {
                "is_regression": False,
                "reason": "not_a_regression",
                "runs": runs,
            }
        elif status_label == "flaky":
            payload = {
                "is_regression": False,
                "reason": "flaky_on_parent",
                "runs": runs,
            }
        else:
            payload = {
                "is_regression": False,
                "reason": "collection_error",
                "runs": runs,
            }
    finally:
        try:
            git_runner(["worktree", "remove", "--force", str(scratch)], str(worktree_root))
        except Exception:
            pass

    _store_regression_cache(key, payload, cache_dir)
    return RegressionStatus(
        is_regression=payload["is_regression"],
        reason=payload["reason"],
        cache_hit=False,
        runs=payload["runs"],
    )


def _default_git_runner(args: List[str], cwd: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise OrchestratorError(
            f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def _default_pytest_runner(commands: List[str], cwd: str, runs: int) -> List[Dict[str, Any]]:
    # Reuse the harness's run_validations to keep semantics identical to the
    # arm-finish path (2-runs-all-must-pass + flake classification).
    return run_validations(commands, cwd, runs)


def _default_collect_commits(worktree_path: str) -> List[str]:
    """Return the worktree's HEAD as the linked commit, falling back to []."""
    try:
        out = _default_git_runner(["rev-parse", "HEAD"], worktree_path).strip()
        return [out] if out else []
    except OrchestratorError:
        return []


# ---------------------------------------------------------------------------
# Arm runner
# ---------------------------------------------------------------------------

@dataclass
class ArmResult:
    arm: str
    trial_id: str
    validation_status: str
    public_valid: bool
    turn_count: int
    total_billed_input: int


# Pluggable type for the SDK's query function. Real impl pulls from
# claude_agent_sdk; tests inject a fake.
SdkQueryFunc = Callable[..., Any]


async def stream_assistant_usage(
    *,
    sdk_query: SdkQueryFunc,
    prompt: str,
    options_kwargs: Dict[str, Any],
    buffer: TurnTokenBuffer,
    timeout_seconds: float,
    is_assistant_message: Callable[[Any], bool],
    extract_message_id_and_usage: Callable[[Any], Tuple[Optional[str], Dict[str, Any]]],
    is_system_message: Callable[[Any], bool] = lambda _m: False,
    on_system_message: Callable[[Any], None] = lambda _m: None,
) -> int:
    """Iterate the SDK event stream and feed AssistantMessage usage into the
    buffer. Returns the count of unique AssistantMessage IDs seen.
    """
    seen_ids: set = set()

    async def _consume():
        async for message in sdk_query(prompt=prompt, options=options_kwargs):
            if is_system_message(message):
                on_system_message(message)
                continue
            if not is_assistant_message(message):
                continue
            mid, usage = extract_message_id_and_usage(message)
            if not mid:
                continue
            seen_ids.add(mid)
            buffer.observe(mid, usage or {})

    await asyncio.wait_for(_consume(), timeout=timeout_seconds)
    return len(seen_ids)


async def run_arm(
    *,
    store: TrialStore,
    pair_id: str,
    arm: str,
    worktree_path: Path,
    model: str,
    prompt: str,
    sdk_query: SdkQueryFunc,
    is_assistant_message: Callable[[Any], bool],
    extract_message_id_and_usage: Callable[[Any], Tuple[Optional[str], Dict[str, Any]]],
    validation_commands: List[str],
    validation_runs: int = 2,
    timeout_hours: float = 4.0,
    audit_dir: Optional[Path] = None,
    dotscope_mcp_command: str = "dotscope-mcp",
    is_system_message: Callable[[Any], bool] = lambda _m: False,
    on_system_message: Callable[[Any], None] = lambda _m: None,
    git_commit_collector: Optional[Callable[[str], List[str]]] = None,
    contamination_stop_at: Optional[Path] = None,
) -> ArmResult:
    """Run one arm of a paired trial.

    1. Layer 3 contamination check (every arm).
    2. Layer 2 tool-inventory check (baseline only) — caller's responsibility
       via `baseline_tool_inventory_check` before calling run_arm.
    3. dotscope trial start.
    4. SDK query() with per-arm options; stream tokens into TurnTokenBuffer.
    5. Flush one record per message_id to the harness.
    6. dotscope trial finish (validation runs through harness).
    """
    assert_no_inherited_mcp_config(
        worktree_path,
        fail_loud=(arm == "baseline"),
        stop_at_directory=contamination_stop_at,
    )

    spec = build_sdk_options(
        arm=arm,
        worktree_path=worktree_path,
        model=model,
        dotscope_mcp_command=dotscope_mcp_command,
    )
    options_kwargs = spec.to_kwargs()

    trial = store.start_trial(
        pair_id=pair_id,
        arm=arm,
        worktree=str(worktree_path),
        token_boundary="agent",
        token_fidelity="A",
        capture_method=CAPTURE_METHOD,
        tokenizer_encoding=model,
        timeout_hours=timeout_hours,
        token_accounting_policy="billed_input_sum",
    )
    trial_id = trial["trial_id"]

    audit_path = (audit_dir / f"{trial_id}.jsonl") if audit_dir else None
    buffer = TurnTokenBuffer(audit_path=audit_path)

    try:
        turn_count = await stream_assistant_usage(
            sdk_query=sdk_query,
            prompt=prompt,
            options_kwargs=options_kwargs,
            buffer=buffer,
            timeout_seconds=timeout_hours * 3600,
            is_assistant_message=is_assistant_message,
            extract_message_id_and_usage=extract_message_id_and_usage,
            is_system_message=is_system_message,
            on_system_message=on_system_message,
        )
    except asyncio.TimeoutError:
        store.cancel_trial(trial_id=trial_id)
        return ArmResult(
            arm=arm,
            trial_id=trial_id,
            validation_status="timeout",
            public_valid=False,
            turn_count=0,
            total_billed_input=buffer.total_billed_input(),
        )
    except Exception:
        store.cancel_trial(trial_id=trial_id)
        raise

    # Flush exactly one harness record per unique message_id with
    # billed_input_sum as the recorded input_tokens.
    for record in buffer.records():
        store.record_tokens(
            input_tokens=record.billed_input_sum,
            token_boundary="agent",
            token_fidelity="A",
            capture_method=CAPTURE_METHOD,
            tokenizer_encoding=model,
            source="agent_sdk",
            turn_id=record.message_id,
            trial_id=trial_id,
            cache_creation_input_tokens=record.cache_creation_input_tokens,
            cache_read_input_tokens=record.cache_read_input_tokens,
        )

    commits = (
        git_commit_collector(str(worktree_path))
        if git_commit_collector
        else _default_collect_commits(str(worktree_path))
    )
    finished = store.finish_trial(
        trial_id=trial_id,
        commits=commits,
        validations=validation_commands,
        validation_runs=validation_runs,
    )
    validation_status = finished["validation_status"]

    return ArmResult(
        arm=arm,
        trial_id=trial_id,
        validation_status=validation_status,
        public_valid=(validation_status in {"success", "failure"}),
        turn_count=turn_count,
        total_billed_input=buffer.total_billed_input(),
    )


# ---------------------------------------------------------------------------
# Layer 2 baseline tool-inventory check
# ---------------------------------------------------------------------------

INVENTORY_PROBE_PROMPT = (
    "List every tool you have access to right now. "
    "Output ONLY a JSON array of tool names. Do not call any tools."
)


async def baseline_tool_inventory_check(
    *,
    sdk_query: SdkQueryFunc,
    worktree_path: Path,
    model: str,
    timeout_seconds: float = 60.0,
    is_assistant_message: Callable[[Any], bool],
    extract_text_content: Callable[[Any], str],
    dotscope_tool_prefix: str = DOTSCOPE_TOOL_PREFIX,
) -> Dict[str, Any]:
    """Spawn a 1-turn baseline session with a forcing introspection prompt.
    Refuses to proceed if any tool name in the response contains the dotscope
    prefix.
    """
    spec = build_sdk_options(arm="baseline", worktree_path=worktree_path, model=model)
    spec.max_turns = 1
    options_kwargs = spec.to_kwargs()

    response_text_parts: List[str] = []

    async def _consume():
        async for message in sdk_query(prompt=INVENTORY_PROBE_PROMPT, options=options_kwargs):
            if is_assistant_message(message):
                response_text_parts.append(extract_text_content(message))

    try:
        await asyncio.wait_for(_consume(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise OrchestratorError("baseline tool-inventory check timed out")

    response_text = "\n".join(response_text_parts).strip()
    advertised: List[str] = []
    try:
        # Accept any JSON array embedded in the response.
        start = response_text.find("[")
        end = response_text.rfind("]")
        if start >= 0 and end > start:
            parsed = json.loads(response_text[start : end + 1])
            if isinstance(parsed, list):
                advertised = [str(item) for item in parsed]
    except (json.JSONDecodeError, ValueError):
        advertised = []

    leaked = [t for t in advertised if dotscope_tool_prefix in t.lower()]
    if leaked:
        raise BaselineContaminationError(
            f"baseline arm advertises dotscope tools: {leaked}. "
            f"setting_sources=['local'] failed to suppress an MCP server."
        )
    return {
        "advertised": advertised,
        "raw_response": response_text,
        "leaked": leaked,
    }


# ---------------------------------------------------------------------------
# Pair driver
# ---------------------------------------------------------------------------

@dataclass
class PairResult:
    pair_id: str
    arm_order: List[str]
    results: List[ArmResult]
    public_valid: bool


async def run_pair(
    *,
    store: TrialStore,
    task: str,
    model: str,
    client: str,
    project: str,
    base_ref: str,
    prompt: str,
    worktrees_root: Path,
    sdk_query: SdkQueryFunc,
    is_assistant_message: Callable[[Any], bool],
    extract_message_id_and_usage: Callable[[Any], Tuple[Optional[str], Dict[str, Any]]],
    git_runner: Callable[[List[str], str], str] = _default_git_runner,
    validation_commands: List[str] = (),
    validation_runs: int = 2,
    timeout_hours: float = 4.0,
    audit_dir: Optional[Path] = None,
    dotscope_mcp_command: str = "dotscope-mcp",
    extract_text_content: Optional[Callable[[Any], str]] = None,
    is_system_message: Callable[[Any], bool] = lambda _m: False,
    on_system_message: Callable[[Any], None] = lambda _m: None,
    skip_baseline_inventory_check: bool = False,
    contamination_stop_at: Optional[Path] = None,
) -> PairResult:
    """Run both arms of a pair and return the combined PairResult."""
    pair = store.create_pair(
        task=task,
        model=model,
        client=client,
        project=project,
        base_ref=base_ref,
        order_policy="random",
    )
    pair_id = pair["pair_id"]
    arm_order = pair["arm_order"]
    results: List[ArmResult] = []

    for arm in arm_order:
        worktree_path = worktrees_root / f"trial_{pair_id}_{arm}"
        if worktree_path.exists():
            git_runner(
                ["worktree", "remove", "--force", str(worktree_path)],
                str(worktrees_root),
            )
        git_runner(["worktree", "add", str(worktree_path), base_ref], str(worktrees_root))

        try:
            if arm == "baseline" and not skip_baseline_inventory_check:
                if extract_text_content is None:
                    raise OrchestratorError(
                        "baseline arm requires extract_text_content for "
                        "tool-inventory check; pass skip_baseline_inventory_check=True "
                        "to bypass (not recommended for public corpus)"
                    )
                await baseline_tool_inventory_check(
                    sdk_query=sdk_query,
                    worktree_path=worktree_path,
                    model=model,
                    is_assistant_message=is_assistant_message,
                    extract_text_content=extract_text_content,
                )

            result = await run_arm(
                store=store,
                pair_id=pair_id,
                arm=arm,
                worktree_path=worktree_path,
                model=model,
                prompt=prompt,
                sdk_query=sdk_query,
                is_assistant_message=is_assistant_message,
                extract_message_id_and_usage=extract_message_id_and_usage,
                validation_commands=list(validation_commands),
                validation_runs=validation_runs,
                timeout_hours=timeout_hours,
                audit_dir=audit_dir,
                dotscope_mcp_command=dotscope_mcp_command,
                is_system_message=is_system_message,
                on_system_message=on_system_message,
                contamination_stop_at=contamination_stop_at,
            )
            results.append(result)
        finally:
            try:
                git_runner(
                    ["worktree", "remove", "--force", str(worktree_path)],
                    str(worktrees_root),
                )
            except Exception:
                pass

    comparison = store.compare_pair(pair_id)
    return PairResult(
        pair_id=pair_id,
        arm_order=list(arm_order),
        results=results,
        public_valid=bool(comparison.get("public_valid")),
    )


# ---------------------------------------------------------------------------
# SDK adapter (lazy-imported so tests don't need the package)
# ---------------------------------------------------------------------------

def load_real_sdk_adapter() -> Dict[str, Any]:
    """Materialize the claude-agent-sdk integration. Lazy import — the SDK is
    optional and only required when running real arms."""
    try:
        from claude_agent_sdk import (  # type: ignore[import-not-found]
            query as sdk_query,
            ClaudeAgentOptions,
            AssistantMessage,
            SystemMessage,
            TextBlock,
        )
    except ImportError as exc:
        raise OrchestratorError(
            "claude-agent-sdk is required to run real arms. "
            "Install with: pip install dotscope[trial-orchestrator]"
        ) from exc

    async def query_wrapper(prompt: str, options: Dict[str, Any]):
        opts = ClaudeAgentOptions(**options)
        async for message in sdk_query(prompt=prompt, options=opts):
            yield message

    def is_assistant(m: Any) -> bool:
        return isinstance(m, AssistantMessage)

    def is_system(m: Any) -> bool:
        return isinstance(m, SystemMessage)

    def extract_id_and_usage(m: Any) -> Tuple[Optional[str], Dict[str, Any]]:
        return getattr(m, "message_id", None), getattr(m, "usage", None) or {}

    def extract_text(m: Any) -> str:
        content = getattr(m, "content", None) or []
        return "".join(
            getattr(block, "text", "") for block in content
            if isinstance(block, TextBlock)
        )

    return {
        "sdk_query": query_wrapper,
        "is_assistant_message": is_assistant,
        "is_system_message": is_system,
        "extract_message_id_and_usage": extract_id_and_usage,
        "extract_text_content": extract_text,
    }
