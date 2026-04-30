"""Live paired-trial harness for defensible dotscope claims."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .engine.tokens import estimate_tokens
from .storage.atomic import atomic_write_json, atomic_write_text


SCHEMA_VERSION = 1
TRIAL_EVENT_SCHEMA_HEADER = {"type": "schema", "version": SCHEMA_VERSION}
PUBLIC_MIN_PAIRS = 30
PUBLIC_MAX_CI_HALF_WIDTH_PP = 5.0
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 1337
PUBLIC_TIMEOUT_HOURS = 8.0

ARMS = {"dotscope", "baseline"}
TOKEN_BOUNDARIES = {"agent", "dotscope"}
TOKEN_FIDELITIES = {"A", "B", "C"}
TOKEN_ACCOUNTING_POLICIES = {"billed_input_sum", "input_only"}


class TrialError(ValueError):
    """Raised when a trial command cannot be completed."""


class PublicReportError(RuntimeError):
    """Raised when a public report is refused by gates."""

    def __init__(self, report: Dict[str, Any]):
        self.report = report
        super().__init__("public report gates failed")


@dataclass
class RepoState:
    head: str
    clean: bool
    repo_state_hash: str
    dirty_paths: List[str]


class TrialStore:
    """Persistent storage for live trial pairs, arms, and events."""

    def __init__(self, repo_root: str):
        self.root = Path(repo_root).resolve()
        self.dot_dir = self.root / ".dotscope"
        self.base_dir = self.dot_dir / "trials"
        self.pairs_dir = self.base_dir / "pairs"
        self.trials_dir = self.base_dir / "arms"
        self.events_dir = self.base_dir / "events"
        self.active_path = self.base_dir / "active.json"

    def ensure_initialized(self) -> None:
        for path in (self.pairs_dir, self.trials_dir, self.events_dir):
            path.mkdir(parents=True, exist_ok=True)

        gitignore = self.dot_dir / ".gitignore"
        if not gitignore.exists():
            atomic_write_text(gitignore, "*\n")

    def create_pair(
        self,
        task: str,
        model: str,
        client: str,
        project: Optional[str] = None,
        base_ref: Optional[str] = None,
        pair_id: Optional[str] = None,
        order_policy: str = "random",
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        if order_policy not in {"random", "alternating"}:
            raise TrialError("order policy must be 'random' or 'alternating'")

        pair_id = pair_id or f"pair_{uuid.uuid4().hex[:12]}"
        path = self.pairs_dir / f"{pair_id}.json"
        if path.exists():
            raise TrialError(f"pair id already exists: {pair_id}")

        project_id = project or default_project_id(str(self.root))
        base_ref = base_ref or "HEAD"
        arm_order = self._choose_arm_order(order_policy)

        pair = {
            "schema_version": SCHEMA_VERSION,
            "pair_id": pair_id,
            "task": task,
            "model": model,
            "client": client,
            "project_id": project_id,
            "project_override": project is not None,
            "base_ref": base_ref,
            "order_policy": order_policy,
            "arm_order": arm_order,
            "created_at": utc_now(),
        }
        atomic_write_json(path, pair)
        return pair

    def start_trial(
        self,
        pair_id: str,
        arm: str,
        worktree: Optional[str] = None,
        token_boundary: str = "agent",
        token_fidelity: str = "C",
        capture_method: str = "",
        tokenizer_encoding: str = "",
        timeout_hours: float = 4.0,
        token_accounting_policy: str = "billed_input_sum",
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        if arm not in ARMS:
            raise TrialError("arm must be 'dotscope' or 'baseline'")
        if token_boundary not in TOKEN_BOUNDARIES:
            raise TrialError("token boundary must be 'agent' or 'dotscope'")
        if token_fidelity not in TOKEN_FIDELITIES:
            raise TrialError("token fidelity must be A, B, or C")
        if timeout_hours <= 0:
            raise TrialError("timeout must be positive")
        if token_accounting_policy not in TOKEN_ACCOUNTING_POLICIES:
            raise TrialError(
                f"token_accounting_policy must be one of "
                f"{sorted(TOKEN_ACCOUNTING_POLICIES)}"
            )

        pair = self.load_pair(pair_id)
        existing_active = self.get_active_trial()
        if existing_active is not None:
            raise TrialError(f"active trial already exists: {existing_active['trial_id']}")

        existing_arms = {
            trial.get("arm")
            for trial in self.load_trials(pair_id=pair_id)
            if trial.get("status") != "cancelled"
        }
        if arm in existing_arms:
            raise TrialError(f"pair {pair_id} already has a non-cancelled {arm} arm")

        worktree_path = Path(worktree).resolve() if worktree else self.root
        state = compute_repo_state(str(worktree_path))
        now = datetime.now(timezone.utc)
        trial_id = f"trial_{uuid.uuid4().hex[:12]}"
        expires_at = now + timedelta(hours=timeout_hours)
        public_timeout_ok = timeout_hours <= PUBLIC_TIMEOUT_HOURS
        pre_registration = load_pre_registration(str(self.root))

        trial = {
            "schema_version": SCHEMA_VERSION,
            "trial_id": trial_id,
            "pair_id": pair_id,
            "arm": arm,
            "status": "active",
            "task": pair["task"],
            "model": pair["model"],
            "client": pair["client"],
            "project_id": pair["project_id"],
            "base_ref": pair["base_ref"],
            "worktree_path": str(worktree_path),
            "repo_state_hash": state.repo_state_hash,
            "head": state.head,
            "clean_start": state.clean,
            "dirty_paths": state.dirty_paths,
            "token_boundary": token_boundary,
            "token_fidelity": token_fidelity,
            "capture_method": capture_method,
            "tokenizer_encoding": tokenizer_encoding,
            "token_accounting_policy": token_accounting_policy,
            "timeout_hours": timeout_hours,
            "public_timeout_ok": public_timeout_ok,
            "started_at": isoformat(now),
            "expires_at": isoformat(expires_at),
            "ended_at": None,
            "validation_status": "unvalidated",
            "validation_runs": [],
            "commits": [],
            "committed_files": [],
            "integrity": {"checked": False, "passed": None, "issues": []},
            "pre_registration": pre_registration,
        }
        atomic_write_json(self.trials_dir / f"{trial_id}.json", trial)
        self._initialize_events(trial_id)
        atomic_write_json(self.active_path, {
            "schema_version": SCHEMA_VERSION,
            "trial_id": trial_id,
            "pair_id": pair_id,
            "arm": arm,
            "started_at": trial["started_at"],
            "expires_at": trial["expires_at"],
        })
        self.append_event(trial_id, {
            "type": "trial_started",
            "source": "dotscope.trial",
            "token_boundary": token_boundary,
            "token_fidelity": token_fidelity,
            "capture_method": capture_method,
            "tokenizer_encoding": tokenizer_encoding,
        })
        return trial

    def finish_trial(
        self,
        trial_id: Optional[str] = None,
        commits: Optional[List[str]] = None,
        validations: Optional[List[str]] = None,
        validation_runs: int = 2,
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        trial = self._resolve_trial(trial_id)
        if trial.get("status") == "cancelled":
            raise TrialError(f"cannot finish cancelled trial: {trial['trial_id']}")
        if validation_runs <= 0:
            raise TrialError("validation runs must be positive")

        commits = commits or []
        validations = validations or []
        validation_results = run_validations(
            validations,
            cwd=trial.get("worktree_path") or str(self.root),
            runs=validation_runs,
        )
        validation_status = classify_validation(validation_results)
        committed_files = collect_commit_files(
            commits,
            cwd=trial.get("worktree_path") or str(self.root),
        )

        trial["status"] = "finished"
        trial["ended_at"] = utc_now()
        trial["commits"] = commits
        trial["committed_files"] = committed_files
        trial["validation_status"] = validation_status
        trial["validation_runs"] = validation_results

        self.append_event(trial["trial_id"], {
            "type": "trial_finished",
            "source": "dotscope.trial",
            "commits": commits,
            "committed_files": committed_files,
            "validation_status": validation_status,
        })

        integrity = self.check_integrity(trial["trial_id"])
        trial["integrity"] = integrity
        self._save_trial(trial)
        self._clear_active_if(trial["trial_id"])
        return trial

    def cancel_trial(self, trial_id: Optional[str] = None) -> Dict[str, Any]:
        self.ensure_initialized()
        trial = self._resolve_trial(trial_id)
        trial["status"] = "cancelled"
        trial["ended_at"] = utc_now()
        self.append_event(trial["trial_id"], {
            "type": "trial_cancelled",
            "source": "dotscope.trial",
        })
        trial["integrity"] = self.check_integrity(trial["trial_id"])
        self._save_trial(trial)
        self._clear_active_if(trial["trial_id"])
        return trial

    def record_tokens(
        self,
        input_tokens: int,
        token_boundary: str,
        token_fidelity: str,
        capture_method: str = "",
        tokenizer_encoding: str = "",
        source: str = "agent",
        turn_id: Optional[str] = None,
        trial_id: Optional[str] = None,
        cache_creation_input_tokens: Optional[int] = None,
        cache_read_input_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        if input_tokens < 0:
            raise TrialError("input tokens must be non-negative")
        if token_boundary not in TOKEN_BOUNDARIES:
            raise TrialError("token boundary must be 'agent' or 'dotscope'")
        if token_fidelity not in TOKEN_FIDELITIES:
            raise TrialError("token fidelity must be A, B, or C")
        if cache_creation_input_tokens is not None and cache_creation_input_tokens < 0:
            raise TrialError("cache_creation_input_tokens must be non-negative")
        if cache_read_input_tokens is not None and cache_read_input_tokens < 0:
            raise TrialError("cache_read_input_tokens must be non-negative")

        trial = self._resolve_trial(trial_id)

        if turn_id is not None:
            existing = self.load_events(trial["trial_id"])
            for prior in existing:
                if (
                    prior.get("type") == "token_usage"
                    and prior.get("turn_id") == turn_id
                ):
                    raise TrialError(
                        f"duplicate turn_id {turn_id!r} for trial "
                        f"{trial['trial_id']}; one record per turn_id"
                    )

        event = {
            "type": "token_usage",
            "source": source,
            "input_tokens": int(input_tokens),
            "token_boundary": token_boundary,
            "token_fidelity": token_fidelity,
            "capture_method": capture_method,
            "tokenizer_encoding": tokenizer_encoding,
            "turn_id": turn_id,
        }
        if cache_creation_input_tokens is not None:
            event["cache_creation_input_tokens"] = int(cache_creation_input_tokens)
        if cache_read_input_tokens is not None:
            event["cache_read_input_tokens"] = int(cache_read_input_tokens)
        return self.append_event(trial["trial_id"], event)

    def record_dotscope_resolve(
        self,
        scope: str,
        files: Iterable[str],
        context: str,
        source: str,
        payload_tokens: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        trial = self.get_active_trial()
        if trial is None:
            return None

        served_files = []
        for path in files:
            served_files.append(file_snapshot(path, str(self.root)))

        event = {
            "type": "dotscope_resolve",
            "source": source,
            "scope": scope,
            "token_boundary": "dotscope",
            "token_fidelity": "C",
            "payload_tokens": int(
                payload_tokens if payload_tokens is not None else estimate_tokens(context or "")
            ),
            "served_files": served_files,
        }
        return self.append_event(trial["trial_id"], event)

    def status(self) -> Dict[str, Any]:
        self.ensure_initialized()
        active = self.get_active_trial()
        trials = self.load_trials()
        pairs = self.load_pairs()
        return {
            "schema_version": SCHEMA_VERSION,
            "active": active,
            "pair_count": len(pairs),
            "trial_count": len(trials),
            "finished_trials": sum(1 for t in trials if t.get("status") == "finished"),
            "cancelled_trials": sum(1 for t in trials if t.get("status") == "cancelled"),
            "expired_trials": sum(1 for t in trials if t.get("status") == "expired"),
        }

    def compare_pair(self, pair_id: str) -> Dict[str, Any]:
        pair = self.load_pair(pair_id)
        trials = self.load_trials(pair_id=pair_id)
        return analyze_pair(pair, trials, self)

    def report(self, public: bool = False) -> Dict[str, Any]:
        pairs = self.load_pairs()
        analyses = [
            analyze_pair(pair, self.load_trials(pair_id=pair["pair_id"]), self)
            for pair in pairs
        ]
        valid = [item for item in analyses if item["public_valid"]]
        metrics = build_public_metrics(valid)
        gates = build_public_gates(valid, metrics) if public else []
        pre_registration = load_pre_registration(str(self.root))
        deviations = (pre_registration or {}).get("deviations") or []

        report = {
            "schema_version": SCHEMA_VERSION,
            "public": public,
            "generated_at": utc_now(),
            "pair_count": len(pairs),
            "valid_public_pairs": len(valid),
            "invalid_pairs": [
                {
                    "pair_id": item["pair_id"],
                    "reasons": item["reasons"],
                }
                for item in analyses
                if not item["public_valid"]
            ],
            "metrics": metrics,
            "gates": gates,
            "statistics": {
                "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                "bootstrap_method": "percentile",
                "bootstrap_seed": BOOTSTRAP_SEED,
                "success_rate_interval": "wilson",
                "minimum_pairs": PUBLIC_MIN_PAIRS,
                "max_ci_half_width_pp": PUBLIC_MAX_CI_HALF_WIDTH_PP,
            },
            "projects": build_project_groups(valid),
            "pre_registration": pre_registration,
            "deviations": deviations,
        }
        if public and not all(gate["passed"] for gate in gates):
            raise PublicReportError(report)
        return report

    def load_pair(self, pair_id: str) -> Dict[str, Any]:
        path = self.pairs_dir / f"{pair_id}.json"
        if not path.exists():
            raise TrialError(f"pair not found: {pair_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def load_pairs(self) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        pairs = []
        for path in sorted(self.pairs_dir.glob("*.json")):
            try:
                pairs.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return pairs

    def load_trial(self, trial_id: str) -> Dict[str, Any]:
        path = self.trials_dir / f"{trial_id}.json"
        if not path.exists():
            raise TrialError(f"trial not found: {trial_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def load_trials(self, pair_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        trials = []
        for path in sorted(self.trials_dir.glob("*.json")):
            try:
                trial = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if pair_id is None or trial.get("pair_id") == pair_id:
                trials.append(trial)
        return trials

    def load_events(self, trial_id: str) -> List[Dict[str, Any]]:
        path = self.events_dir / f"{trial_id}.jsonl"
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return []
        events = []
        for line in lines[1:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"type": "corrupt_event", "raw": line})
        return events

    def get_active_trial(self) -> Optional[Dict[str, Any]]:
        if not self.active_path.exists():
            return None
        try:
            active = json.loads(self.active_path.read_text(encoding="utf-8"))
            trial = self.load_trial(active["trial_id"])
        except (KeyError, TrialError, json.JSONDecodeError, OSError):
            return None
        if trial.get("status") != "active":
            return None
        if is_expired(trial.get("expires_at")):
            self.append_event(trial["trial_id"], {
                "type": "trial_expired",
                "source": "dotscope.trial",
            })
            trial["status"] = "expired"
            trial["ended_at"] = utc_now()
            trial["integrity"] = self.check_integrity(trial["trial_id"])
            self._save_trial(trial)
            self._clear_active_if(trial["trial_id"])
            return None
        return trial

    def append_event(self, trial_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        self.ensure_initialized()
        path = self.events_dir / f"{trial_id}.jsonl"
        self._initialize_events(trial_id)

        events = self.load_events(trial_id)
        trial = self.load_trial(trial_id)
        payload = dict(event)
        payload.update({
            "schema_version": SCHEMA_VERSION,
            "event_id": len(events) + 1,
            "timestamp": utc_now(),
            "trial_id": trial_id,
            "pair_id": trial.get("pair_id"),
            "arm": trial.get("arm"),
        })
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload

    def check_integrity(self, trial_id: str) -> Dict[str, Any]:
        path = self.events_dir / f"{trial_id}.jsonl"
        issues = []
        if not path.exists():
            issues.append("events file missing")
            return {"checked": True, "passed": False, "issues": issues}

        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            issues.append("events file empty")
            return {"checked": True, "passed": False, "issues": issues}

        try:
            schema = json.loads(lines[0])
        except json.JSONDecodeError:
            issues.append("schema header is not valid JSON")
            schema = {}
        if schema != TRIAL_EVENT_SCHEMA_HEADER:
            issues.append("schema header missing or unsupported")

        expected_id = 1
        for line in lines[1:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                issues.append(f"event {expected_id} is not valid JSON")
                expected_id += 1
                continue
            if event.get("event_id") != expected_id:
                issues.append(f"event id gap at {expected_id}")
            for item in event.get("served_files", []) or []:
                if not item.get("sha256"):
                    issues.append(f"served file was not hashable: {item.get('path', '<unknown>')}")
            expected_id += 1

        return {"checked": True, "passed": not issues, "issues": issues}

    def _save_trial(self, trial: Dict[str, Any]) -> None:
        atomic_write_json(self.trials_dir / f"{trial['trial_id']}.json", trial)

    def _resolve_trial(self, trial_id: Optional[str]) -> Dict[str, Any]:
        if trial_id:
            return self.load_trial(trial_id)
        active = self.get_active_trial()
        if active is None:
            raise TrialError("no active trial")
        return active

    def _initialize_events(self, trial_id: str) -> None:
        path = self.events_dir / f"{trial_id}.jsonl"
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return
        atomic_write_text(path, json.dumps(TRIAL_EVENT_SCHEMA_HEADER) + "\n")

    def _clear_active_if(self, trial_id: str) -> None:
        if not self.active_path.exists():
            return
        try:
            active = json.loads(self.active_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if active.get("trial_id") == trial_id:
            self.active_path.unlink()

    def _choose_arm_order(self, order_policy: str) -> List[str]:
        if order_policy == "alternating":
            count = len(list(self.pairs_dir.glob("*.json"))) if self.pairs_dir.exists() else 0
            return ["dotscope", "baseline"] if count % 2 == 0 else ["baseline", "dotscope"]
        arms = ["dotscope", "baseline"]
        random.SystemRandom().shuffle(arms)
        return arms


def record_active_dotscope_resolve(
    repo_root: Optional[str],
    scope: str,
    files: Iterable[str],
    context: str,
    source: str,
    payload_tokens: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if repo_root is None:
        return None
    try:
        return TrialStore(repo_root).record_dotscope_resolve(
            scope,
            files,
            context,
            source,
            payload_tokens=payload_tokens,
        )
    except Exception:
        return None


def compute_repo_state(repo_root: str) -> RepoState:
    head = run_git(["rev-parse", "HEAD"], repo_root).strip()
    status = run_git(["status", "--porcelain", "--untracked-files=all"], repo_root)
    dirty_paths = []
    for line in status.splitlines():
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if path.startswith(".dotscope/") or path == ".dotscope":
            continue
        dirty_paths.append(path)
    clean = not dirty_paths
    repo_state_hash = f"{head}:clean" if clean else f"{head}:dirty"
    return RepoState(
        head=head,
        clean=clean,
        repo_state_hash=repo_state_hash,
        dirty_paths=dirty_paths,
    )


PRE_REGISTRATION_SIDECAR = "docs/trial-pre-registration.json"
PRE_REGISTRATION_DOC = "docs/trial-pre-registration.md"


def load_pre_registration(repo_root: str) -> Optional[Dict[str, Any]]:
    """Load the pre-registration sidecar and verify the doc hash.

    Returns the parsed sidecar dict if present and the doc hash matches.
    Returns None if the sidecar is absent (allowing trials to run in
    repos without a registration, e.g. test fixtures).
    Raises TrialError if the sidecar exists but the doc is missing or
    its hash does not match doc_sha256 in the sidecar.
    """
    root = Path(repo_root).resolve()
    sidecar_path = root / PRE_REGISTRATION_SIDECAR
    doc_path = root / PRE_REGISTRATION_DOC
    if not sidecar_path.exists():
        return None

    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise TrialError(f"pre-registration sidecar is unreadable: {exc}")

    expected_hash = sidecar.get("doc_sha256")
    if not expected_hash:
        raise TrialError("pre-registration sidecar missing doc_sha256")
    if not doc_path.exists():
        raise TrialError(
            f"pre-registration sidecar present but doc missing: {PRE_REGISTRATION_DOC}"
        )

    actual_hash = hashlib.sha256(doc_path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise TrialError(
            f"pre-registration doc hash mismatch: expected {expected_hash}, got {actual_hash}"
        )

    return {
        "commit": sidecar.get("registered_commit") or "",
        "tag": sidecar.get("tag") or "",
        "doc_sha256": expected_hash,
        "harness_tag": sidecar.get("harness_tag") or "",
        "harness_commit": sidecar.get("harness_commit") or "",
        "deviations": sidecar.get("deviations") or [],
    }


def default_project_id(repo_root: str) -> str:
    try:
        remote = run_git(["config", "--get", "remote.origin.url"], repo_root).strip()
    except TrialError:
        remote = ""
    source = normalize_remote(remote) if remote else str(Path(repo_root).resolve())
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"project_{digest}"


def normalize_remote(remote: str) -> str:
    value = remote.strip().lower()
    if value.endswith(".git"):
        value = value[:-4]
    return value


def run_validations(commands: List[str], cwd: str, runs: int) -> List[Dict[str, Any]]:
    if not commands:
        return []

    results = []
    for run_index in range(runs):
        for command in commands:
            start = time.perf_counter()
            try:
                proc = subprocess.run(
                    command,
                    cwd=cwd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                return_code = proc.returncode
                stdout = proc.stdout[-4000:]
                stderr = proc.stderr[-4000:]
            except subprocess.TimeoutExpired as exc:
                return_code = 124
                stdout = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
                stderr = "validation timed out"
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            results.append({
                "run": run_index + 1,
                "command": command,
                "argv_hint": shlex.split(command) if command else [],
                "return_code": return_code,
                "passed": return_code == 0,
                "duration_ms": duration_ms,
                "stdout": stdout,
                "stderr": stderr,
            })
    return results


def classify_validation(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "unvalidated"
    by_run: Dict[int, List[bool]] = {}
    for result in results:
        by_run.setdefault(int(result["run"]), []).append(bool(result["passed"]))
    run_passes = [all(values) for _, values in sorted(by_run.items())]
    if all(run_passes):
        return "success"
    if not any(run_passes):
        return "failure"
    return "flaky"


def collect_commit_files(commits: List[str], cwd: str) -> List[str]:
    files = set()
    for commit in commits:
        commit = commit.strip()
        if not commit:
            continue
        args = ["diff", "--name-only", commit] if ".." in commit else [
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit,
        ]
        try:
            output = run_git(args, cwd)
        except TrialError:
            continue
        files.update(line.strip() for line in output.splitlines() if line.strip())
    return sorted(files)


def analyze_pair(
    pair: Dict[str, Any],
    trials: List[Dict[str, Any]],
    store: TrialStore,
) -> Dict[str, Any]:
    reasons = []
    pair_id = pair.get("pair_id", "")
    active_trials = [trial for trial in trials if trial.get("status") != "cancelled"]
    if len(active_trials) != 2:
        reasons.append(f"expected exactly 2 non-cancelled trials, found {len(active_trials)}")

    arms = {}
    for trial in active_trials:
        arm = trial.get("arm")
        if arm in arms:
            reasons.append(f"duplicate arm: {arm}")
        arms[arm] = trial

    if set(arms) != ARMS:
        reasons.append("pair must contain exactly one dotscope arm and one baseline arm")

    agreement_keys = [
        "task",
        "model",
        "client",
        "project_id",
        "repo_state_hash",
        "token_boundary",
        "token_fidelity",
        "token_accounting_policy",
    ]
    if len(active_trials) == 2:
        for key in agreement_keys:
            values = {trial.get(key) for trial in active_trials}
            if len(values) != 1:
                reasons.append(f"agreement mismatch: {key}")
        pre_reg_hashes = {
            (trial.get("pre_registration") or {}).get("doc_sha256")
            for trial in active_trials
        }
        if len(pre_reg_hashes) != 1:
            reasons.append("agreement mismatch: pre_registration.doc_sha256")
        for key in ("task", "model", "client", "project_id"):
            if pair.get(key) is not None:
                for trial in active_trials:
                    if trial.get(key) != pair.get(key):
                        reasons.append(f"trial {trial.get('trial_id')} disagrees with pair {key}")

    for trial in active_trials:
        if trial.get("status") != "finished":
            reasons.append(f"trial {trial.get('trial_id')} is not finished")
        if not trial.get("clean_start"):
            reasons.append(f"trial {trial.get('trial_id')} did not start clean")
        if not trial.get("public_timeout_ok", True):
            reasons.append(f"trial {trial.get('trial_id')} exceeds public timeout cap")
        integrity = trial.get("integrity") or {}
        if not integrity.get("checked") or not integrity.get("passed"):
            reasons.append(f"trial {trial.get('trial_id')} failed integrity")
        if trial.get("validation_status") not in {"success", "failure"}:
            reasons.append(
                f"trial {trial.get('trial_id')} validation is "
                f"{trial.get('validation_status')}"
            )
        if not trial.get("commits"):
            reasons.append(f"trial {trial.get('trial_id')} has no linked commits")

    token_totals: Dict[str, int] = {}
    if len(active_trials) == 2:
        boundary = active_trials[0].get("token_boundary")
        fidelity = active_trials[0].get("token_fidelity")
        if boundary != "agent":
            reasons.append("public token claims require agent-boundary measurement")
        if fidelity not in {"A", "B"}:
            reasons.append("public token claims require fidelity A or B")
        if fidelity == "B":
            methods = {trial.get("capture_method") for trial in active_trials}
            encodings = {trial.get("tokenizer_encoding") for trial in active_trials}
            if len(methods) != 1 or not next(iter(methods), ""):
                reasons.append("Tier B trials must share a non-empty capture method")
            if len(encodings) != 1 or not next(iter(encodings), ""):
                reasons.append("Tier B trials must share a non-empty tokenizer encoding")

        for trial in active_trials:
            total, token_reasons = public_agent_token_total(
                trial,
                store.load_events(trial["trial_id"]),
            )
            token_totals[trial["arm"]] = total
            reasons.extend(token_reasons)

        if token_totals.get("baseline", 0) <= 0:
            reasons.append("baseline arm has no positive agent-boundary token total")

    dotscope_trial = arms.get("dotscope", {})
    baseline_trial = arms.get("baseline", {})
    token_delta_pct = None
    if token_totals.get("baseline", 0) > 0 and "dotscope" in token_totals:
        token_delta_pct = (
            (token_totals["baseline"] - token_totals["dotscope"])
            / token_totals["baseline"]
        ) * 100.0

    success_delta_pp = None
    if dotscope_trial and baseline_trial:
        d_success = 1 if dotscope_trial.get("validation_status") == "success" else 0
        b_success = 1 if baseline_trial.get("validation_status") == "success" else 0
        success_delta_pp = float(d_success - b_success) * 100.0

    return {
        "pair_id": pair_id,
        "project_id": pair.get("project_id"),
        "project_override": bool(pair.get("project_override")),
        "public_valid": not reasons,
        "reasons": reasons,
        "arms": {
            "dotscope": summarize_trial(dotscope_trial, token_totals.get("dotscope")),
            "baseline": summarize_trial(baseline_trial, token_totals.get("baseline")),
        },
        "paired_token_delta_pct": token_delta_pct,
        "paired_success_delta_pp": success_delta_pp,
    }


def public_agent_token_total(
    trial: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> tuple[int, List[str]]:
    reasons = []
    total = 0
    token_events = [event for event in events if event.get("type") == "token_usage"]
    agent_events = [event for event in token_events if event.get("token_boundary") == "agent"]
    if not agent_events:
        return 0, [f"trial {trial.get('trial_id')} has no agent-boundary token events"]

    for event in agent_events:
        if event.get("token_fidelity") == "C":
            reasons.append(
                f"trial {trial.get('trial_id')} includes "
                f"Tier C token event {event.get('event_id')}"
            )
        if event.get("token_fidelity") != trial.get("token_fidelity"):
            reasons.append(
                f"trial {trial.get('trial_id')} token fidelity mismatch "
                f"at event {event.get('event_id')}"
            )
        if event.get("token_boundary") != trial.get("token_boundary"):
            reasons.append(
                f"trial {trial.get('trial_id')} token boundary mismatch "
                f"at event {event.get('event_id')}"
            )
        total += int(event.get("input_tokens") or 0)
    return total, reasons


def summarize_trial(trial: Dict[str, Any], token_total: Optional[int]) -> Dict[str, Any]:
    if not trial:
        return {}
    return {
        "trial_id": trial.get("trial_id"),
        "status": trial.get("status"),
        "validation_status": trial.get("validation_status"),
        "token_total": token_total,
        "commits": trial.get("commits", []),
        "committed_files": trial.get("committed_files", []),
    }


def build_public_metrics(valid_pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    token_values = [
        item["paired_token_delta_pct"]
        for item in valid_pairs
        if item.get("paired_token_delta_pct") is not None
    ]
    success_values = [
        item["paired_success_delta_pp"]
        for item in valid_pairs
        if item.get("paired_success_delta_pp") is not None
    ]

    metrics: Dict[str, Any] = {}
    metrics["paired_token_delta_pct"] = bootstrap_metric(token_values)
    metrics["paired_success_delta_pp"] = bootstrap_metric(success_values)

    for arm in ("dotscope", "baseline"):
        successes = [
            1 if item["arms"][arm].get("validation_status") == "success" else 0
            for item in valid_pairs
            if item["arms"].get(arm)
        ]
        metrics[f"{arm}_success_rate"] = wilson_metric(successes)

    return metrics


def build_public_gates(
    valid_pairs: List[Dict[str, Any]],
    metrics: Dict[str, Any],
) -> List[Dict[str, Any]]:
    token_ci = metrics["paired_token_delta_pct"].get("ci_half_width_pp")
    success_ci = metrics["paired_success_delta_pp"].get("ci_half_width_pp")
    dotscope_success_ci = metrics["dotscope_success_rate"].get("ci_half_width_pp")
    baseline_success_ci = metrics["baseline_success_rate"].get("ci_half_width_pp")
    return [
        {
            "name": "minimum_pairs",
            "passed": len(valid_pairs) >= PUBLIC_MIN_PAIRS,
            "value": len(valid_pairs),
            "threshold": PUBLIC_MIN_PAIRS,
            "detail": (
                f"N is valid pairs, so {PUBLIC_MIN_PAIRS} means "
                f"{PUBLIC_MIN_PAIRS * 2} trials"
            ),
        },
        {
            "name": "paired_token_delta_ci",
            "passed": token_ci is not None and token_ci <= PUBLIC_MAX_CI_HALF_WIDTH_PP,
            "value": token_ci,
            "threshold": PUBLIC_MAX_CI_HALF_WIDTH_PP,
            "detail": "10,000-resample percentile bootstrap over per-pair token deltas",
        },
        {
            "name": "paired_success_delta_ci",
            "passed": success_ci is not None and success_ci <= PUBLIC_MAX_CI_HALF_WIDTH_PP,
            "value": success_ci,
            "threshold": PUBLIC_MAX_CI_HALF_WIDTH_PP,
            "detail": "10,000-resample percentile bootstrap over per-pair success deltas",
        },
        {
            "name": "dotscope_success_rate_ci",
            "passed": (
                dotscope_success_ci is not None
                and dotscope_success_ci <= PUBLIC_MAX_CI_HALF_WIDTH_PP
            ),
            "value": dotscope_success_ci,
            "threshold": PUBLIC_MAX_CI_HALF_WIDTH_PP,
            "detail": "Wilson interval over dotscope-arm success rate",
        },
        {
            "name": "baseline_success_rate_ci",
            "passed": (
                baseline_success_ci is not None
                and baseline_success_ci <= PUBLIC_MAX_CI_HALF_WIDTH_PP
            ),
            "value": baseline_success_ci,
            "threshold": PUBLIC_MAX_CI_HALF_WIDTH_PP,
            "detail": "Wilson interval over baseline-arm success rate",
        },
    ]


def build_project_groups(valid_pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in valid_pairs:
        groups.setdefault(item.get("project_id") or "unknown", []).append(item)
    return {
        project_id: {
            "valid_public_pairs": len(items),
            "project_override": any(item.get("project_override") for item in items),
            "paired_token_delta_pct": bootstrap_metric([
                item["paired_token_delta_pct"] for item in items
                if item.get("paired_token_delta_pct") is not None
            ]),
            "paired_success_delta_pp": bootstrap_metric([
                item["paired_success_delta_pp"] for item in items
                if item.get("paired_success_delta_pp") is not None
            ]),
        }
        for project_id, items in sorted(groups.items())
    }


def bootstrap_metric(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {
            "mean": None,
            "ci_lower": None,
            "ci_upper": None,
            "ci_half_width_pp": None,
            "n": 0,
            "method": "percentile_bootstrap",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        }
    if len(values) == 1:
        mean = values[0]
        return {
            "mean": round(mean, 3),
            "ci_lower": round(mean, 3),
            "ci_upper": round(mean, 3),
            "ci_half_width_pp": 0.0,
            "n": 1,
            "method": "percentile_bootstrap",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        }

    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    count = len(values)
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample_total = 0.0
        for _item in range(count):
            sample_total += values[rng.randrange(count)]
        means.append(sample_total / count)
    means.sort()
    lower = percentile_sorted(means, 0.025)
    upper = percentile_sorted(means, 0.975)
    mean = sum(values) / count
    return {
        "mean": round(mean, 3),
        "ci_lower": round(lower, 3),
        "ci_upper": round(upper, 3),
        "ci_half_width_pp": round((upper - lower) / 2.0, 3),
        "n": count,
        "method": "percentile_bootstrap",
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
    }


def wilson_metric(values: List[int]) -> Dict[str, Any]:
    n = len(values)
    if n == 0:
        return {
            "rate": None,
            "ci_lower": None,
            "ci_upper": None,
            "ci_half_width_pp": None,
            "n": 0,
            "method": "wilson",
        }
    successes = sum(values)
    z = 1.959963984540054
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (
        z
        * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
        / denom
    )
    return {
        "rate": round(phat * 100.0, 3),
        "ci_lower": round(max(0.0, center - margin) * 100.0, 3),
        "ci_upper": round(min(1.0, center + margin) * 100.0, 3),
        "ci_half_width_pp": round(
            (min(1.0, center + margin) - max(0.0, center - margin)) * 50.0,
            3,
        ),
        "n": n,
        "method": "wilson",
    }


def percentile_sorted(values: List[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = quantile * (len(values) - 1)
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return values[int(index)]
    weight = index - low
    return values[low] * (1 - weight) + values[high] * weight


def file_snapshot(path: str, repo_root: str) -> Dict[str, Any]:
    raw = Path(path)
    full = raw if raw.is_absolute() else Path(repo_root) / raw
    try:
        data = full.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        size = len(data)
        hashable = True
    except OSError:
        digest = ""
        size = 0
        hashable = False
    rel = path
    try:
        rel = str(full.resolve().relative_to(Path(repo_root).resolve())).replace(os.sep, "/")
    except (ValueError, OSError):
        rel = str(path).replace(os.sep, "/")
    return {"path": rel, "sha256": digest, "bytes": size, "hashable": hashable}


def run_git(args: List[str], cwd: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise TrialError(f"git command failed: {' '.join(args)}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise TrialError(f"git command failed: {' '.join(args)}: {detail}")
    return proc.stdout


def format_trial_report(report: Dict[str, Any]) -> str:
    lines = ["dotscope trial report"]
    lines.append(f"  valid public pairs: {report['valid_public_pairs']}/{report['pair_count']}")

    if report.get("gates"):
        lines.append("")
        lines.append("  Public gates")
        for gate in report["gates"]:
            status = "PASS" if gate["passed"] else "FAIL"
            lines.append(
                f"    {status} {gate['name']}: "
                f"{gate['value']} (threshold {gate['threshold']})"
            )

    metrics = report.get("metrics", {})
    if metrics:
        lines.append("")
        lines.append("  Metrics")
        token = metrics.get("paired_token_delta_pct", {})
        success = metrics.get("paired_success_delta_pp", {})
        if token.get("mean") is not None:
            lines.append(
                "    paired_token_delta_pct: "
                f"{token['mean']:.3f}% "
                f"[{token['ci_lower']:.3f}, {token['ci_upper']:.3f}]"
            )
        else:
            lines.append("    paired_token_delta_pct: unavailable")
        if success.get("mean") is not None:
            lines.append(
                "    paired_success_delta_pp: "
                f"{success['mean']:.3f}pp "
                f"[{success['ci_lower']:.3f}, {success['ci_upper']:.3f}]"
            )
        else:
            lines.append("    paired_success_delta_pp: unavailable")

    invalid = report.get("invalid_pairs", [])
    if invalid:
        lines.append("")
        lines.append("  Invalid pairs")
        for item in invalid[:10]:
            reasons = "; ".join(item["reasons"][:3])
            lines.append(f"    {item['pair_id']}: {reasons}")
        if len(invalid) > 10:
            lines.append(f"    ... {len(invalid) - 10} more")

    return "\n".join(lines)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now() -> str:
    return isoformat(datetime.now(timezone.utc))


def is_expired(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) > expires_at
