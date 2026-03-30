"""Core eval harness: gates, primary/secondary fitness, scalar fitness function.

Evaluates dotscope candidates by replaying a corpus of historical commits
and measuring edit frontier quality under cost/freshness constraints.
"""

import os
import time
from typing import List, Optional

from ..models.eval import (
    DownstreamScore,
    EditFrontierScore,
    EvalRun,
    GateResult,
)
from ..models.state import ObservationLog, SessionLog
from ..storage.timing import load_timings, percentile


# ---------------------------------------------------------------------------
# Hard gates
# ---------------------------------------------------------------------------

# Latency budgets (milliseconds)
RESOLVE_P95_BUDGET_MS = 500
CHECK_P95_BUDGET_MS = 1000

# Correctness tolerance: candidate recall may be at most this far below baseline
RECALL_REGRESSION_TOLERANCE = 0.02


def evaluate_gates(
    candidate_obs: List[ObservationLog],
    baseline_obs: List[ObservationLog],
    repo_root: str,
    platform_crashes: int = 0,
    auto_scope_writes: int = 0,
) -> List[GateResult]:
    """Evaluate all hard gates. Every gate must pass for fitness > 0."""
    gates: List[GateResult] = []

    # G1: Correctness — no recall regression
    cand_recall = _mean([o.recall for o in candidate_obs]) if candidate_obs else 0.0
    base_recall = _mean([o.recall for o in baseline_obs]) if baseline_obs else 0.0
    threshold = base_recall - RECALL_REGRESSION_TOLERANCE
    gates.append(GateResult(
        name="correctness",
        passed=cand_recall >= threshold,
        value=round(cand_recall, 4),
        threshold=round(threshold, 4),
        detail=f"candidate recall {cand_recall:.3f} vs baseline {base_recall:.3f}",
    ))

    # G2: Freshness — stale-context failure rate must not increase
    # When no baseline exists, auto-pass (nothing to regress against)
    cand_stale = _stale_rate(candidate_obs)
    base_stale = _stale_rate(baseline_obs) if baseline_obs else 1.0
    gates.append(GateResult(
        name="freshness",
        passed=cand_stale <= base_stale,
        value=round(cand_stale, 4),
        threshold=round(base_stale, 4),
        detail=f"stale rate {cand_stale:.3f} vs baseline {base_stale:.3f}",
    ))

    # G3: Stability — zero crashes across platform matrix
    gates.append(GateResult(
        name="stability",
        passed=platform_crashes == 0,
        value=float(platform_crashes),
        threshold=0.0,
        detail=f"{platform_crashes} crash(es)",
    ))

    # G4: Resolve latency
    timings = load_timings(repo_root)
    resolve_times = [t.duration_ms for t in timings if t.operation == "resolve"]
    p95_resolve = percentile(resolve_times, 95) if resolve_times else 0.0
    gates.append(GateResult(
        name="resolve_latency",
        passed=p95_resolve <= RESOLVE_P95_BUDGET_MS,
        value=round(p95_resolve, 1),
        threshold=float(RESOLVE_P95_BUDGET_MS),
        detail=f"p95 resolve {p95_resolve:.0f}ms",
    ))

    # G5: Check latency
    check_times = [t.duration_ms for t in timings if t.operation == "check"]
    p95_check = percentile(check_times, 95) if check_times else 0.0
    gates.append(GateResult(
        name="check_latency",
        passed=p95_check <= CHECK_P95_BUDGET_MS,
        value=round(p95_check, 1),
        threshold=float(CHECK_P95_BUDGET_MS),
        detail=f"p95 check {p95_check:.0f}ms",
    ))

    # G6: No worktree churn from automatic scope writes
    gates.append(GateResult(
        name="no_worktree_churn",
        passed=auto_scope_writes == 0,
        value=float(auto_scope_writes),
        threshold=0.0,
        detail=f"{auto_scope_writes} auto scope write(s)",
    ))

    return gates


# ---------------------------------------------------------------------------
# Primary fitness: edit frontier quality
# ---------------------------------------------------------------------------

def compute_primary(
    observations: List[ObservationLog],
    constraints_violated: Optional[List[List[str]]] = None,
    constraints_surfaced: Optional[List[List[str]]] = None,
    recommended_tests: Optional[List[List[str]]] = None,
    actual_tests: Optional[List[List[str]]] = None,
    stale_file_counts: Optional[List[int]] = None,
    total_predicted_counts: Optional[List[int]] = None,
) -> EditFrontierScore:
    """Compute primary fitness from observation data.

    Args:
        observations: Per-task observation logs with recall/precision.
        constraints_violated: Per-task list of constraint IDs that fired post-hoc.
        constraints_surfaced: Per-task list of constraint IDs surfaced during resolve.
        recommended_tests: Per-task list of test files recommended by check.
        actual_tests: Per-task list of test files actually needed (modified/failed).
        stale_file_counts: Per-task count of predicted files that were stale.
        total_predicted_counts: Per-task count of total predicted files.
    """
    if not observations:
        return EditFrontierScore()

    # R, P, F1, F2 — per-observation, then averaged
    recalls = [o.recall for o in observations]
    precisions = [o.precision for o in observations]
    f1s = []
    f2s = []
    for r, p in zip(recalls, precisions):
        f1s.append(2 * r * p / (r + p) if (r + p) > 0 else 0.0)
        # F-beta with beta=2: weights recall 2x over precision
        f2s.append(5 * r * p / (4 * p + r) if (4 * p + r) > 0 else 0.0)

    mean_r = _mean(recalls)
    mean_p = _mean(precisions)
    mean_f1 = _mean(f1s)
    mean_f2 = _mean(f2s)

    # IR — invariant recall
    ir = _invariant_recall(constraints_violated, constraints_surfaced)

    # TP — test precision
    tp = _test_precision(recommended_tests, actual_tests)

    # FA — freshness accuracy
    fa = _freshness_accuracy(stale_file_counts, total_predicted_counts)

    return EditFrontierScore(
        mean_recall=round(mean_r, 4),
        mean_precision=round(mean_p, 4),
        mean_f1=round(mean_f1, 4),
        mean_f2=round(mean_f2, 4),
        invariant_recall=round(ir, 4),
        test_precision=round(tp, 4),
        freshness_accuracy=round(fa, 4),
    )


# ---------------------------------------------------------------------------
# Secondary fitness: downstream developer outcome
# ---------------------------------------------------------------------------

def compute_secondary(
    observations: List[ObservationLog],
    tasks_completed_first_try: int = 0,
    total_tasks: int = 0,
    tests_passed_first_run: int = 0,
    tests_run_first_run: int = 0,
    total_expansions: int = 0,
    total_tokens_served: int = 0,
    budget_cap: int = 1,
    holds_surfaced: int = 0,
    holds_overridden: int = 0,
    warnings_issued: int = 0,
    warnings_matched: int = 0,
) -> DownstreamScore:
    """Compute secondary fitness from aggregate task metrics."""
    ts = tasks_completed_first_try / max(total_tasks, 1)
    tpr = tests_passed_first_run / max(tests_run_first_run, 1)
    se = 1.0 - min(total_expansions / max(2 * total_tasks, 1), 1.0)

    # Irrelevant files: from observations
    total_predicted = 0
    total_irrelevant = 0
    for obs in observations:
        total_predicted += len(obs.actual_files_modified) + len(obs.predicted_not_touched)
        total_irrelevant += len(obs.predicted_not_touched)
    irr = 1.0 - (total_irrelevant / max(total_predicted, 1))

    tc = 1.0 - min(total_tokens_served / max(budget_cap, 1), 1.0)
    ho = 1.0 - (holds_overridden / max(holds_surfaced, 1))
    fw = 1.0 - ((warnings_issued - warnings_matched) / max(warnings_issued, 1))

    return DownstreamScore(
        task_success=round(ts, 4),
        test_pass_rate=round(tpr, 4),
        scope_expansions=round(se, 4),
        irrelevant_files=round(irr, 4),
        token_cost=round(tc, 4),
        override_rate=round(ho, 4),
        false_warning_rate=round(max(fw, 0.0), 4),
    )


# ---------------------------------------------------------------------------
# Scalar fitness function
# ---------------------------------------------------------------------------

def fitness(
    gates: List[GateResult],
    primary: EditFrontierScore,
    secondary: DownstreamScore,
) -> float:
    """Scalar fitness for autoresearch candidate ranking.

    Returns 0.0 if any gate fails.
    Primary composite dominates [0.0, 1.0].
    Secondary contributes at most 0.01 (tie-breaker only).
    """
    if not all(g.passed for g in gates):
        return 0.0

    return round(primary.composite + 0.01 * secondary.composite, 4)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stale_rate(observations: List[ObservationLog]) -> float:
    """Fraction of observations with any touched-not-predicted files."""
    if not observations:
        return 0.0
    stale = sum(1 for o in observations if o.touched_not_predicted)
    return stale / len(observations)


def _invariant_recall(
    violated: Optional[List[List[str]]],
    surfaced: Optional[List[List[str]]],
) -> float:
    """IR = |surfaced ∩ violated| / |violated| across all tasks."""
    if not violated or not surfaced:
        return 1.0

    total_violated = 0
    total_surfaced_and_violated = 0
    for v_list, s_list in zip(violated, surfaced):
        v_set = set(v_list)
        s_set = set(s_list)
        total_violated += len(v_set)
        total_surfaced_and_violated += len(v_set & s_set)

    if total_violated == 0:
        return 1.0
    return total_surfaced_and_violated / total_violated


def _test_precision(
    recommended: Optional[List[List[str]]],
    actual: Optional[List[List[str]]],
) -> float:
    """TP = |recommended ∩ actual| / |recommended| across all tasks."""
    if not recommended or not actual:
        return 1.0

    total_recommended = 0
    total_hit = 0
    for r_list, a_list in zip(recommended, actual):
        r_set = set(r_list)
        a_set = set(a_list)
        total_recommended += len(r_set)
        total_hit += len(r_set & a_set)

    if total_recommended == 0:
        return 1.0
    return total_hit / total_recommended


def _freshness_accuracy(
    stale_counts: Optional[List[int]],
    total_counts: Optional[List[int]],
) -> float:
    """FA = 1.0 - (total_stale / total_predicted)."""
    if not stale_counts or not total_counts:
        return 1.0

    total_stale = sum(stale_counts)
    total_predicted = sum(total_counts)
    if total_predicted == 0:
        return 1.0
    return 1.0 - (total_stale / total_predicted)
