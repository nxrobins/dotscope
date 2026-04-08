"""Benchmarking: prove dotscope works with numbers.

Three metrics: token efficiency, hold rate, compilation speed.
Plus scope health aggregation.
"""

import os
from typing import Dict, List, Optional

from ..models.state import BenchReport  # noqa: F401
from ..storage.timing import load_timings, median, percentile


def run_bench(repo_root: str) -> BenchReport:
    """Compute all benchmark metrics from stored data."""
    report = BenchReport()

    # Load data
    from ..storage.session_manager import SessionManager
    mgr = SessionManager(repo_root)
    sessions = mgr.get_sessions(limit=500)
    observations = mgr.get_observations(limit=500)

    # Token efficiency
    tokens_resolved = []
    tokens_used = []
    for obs in observations:
        predicted = set(getattr(obs, "predicted_not_touched", []) or [])
        actual = set(getattr(obs, "actual_files_modified", []) or [])
        all_predicted = set(getattr(obs, "predicted_not_touched", []) or []) | actual
        if all_predicted:
            tokens_resolved.append(len(all_predicted))
            tokens_used.append(len(actual))

    if tokens_resolved:
        report.avg_tokens_resolved = int(sum(tokens_resolved) / len(tokens_resolved))
        report.avg_tokens_used = int(sum(tokens_used) / len(tokens_used))
        report.efficiency_ratio = round(
            sum(tokens_used) / max(sum(tokens_resolved), 1), 3
        )

    # Hold rate (from acknowledgments)
    report.total_commits = len(observations)
    try:
        from ..passes.sentinel.acknowledge import load_acknowledgments
        acks = load_acknowledgments(repo_root)
        report.holds_acknowledged = len(acks)
    except Exception:
        pass

    # Compilation speed
    timings = load_timings(repo_root)
    resolve_times = [t.duration_ms for t in timings if t.operation == "resolve"]
    check_times = [t.duration_ms for t in timings if t.operation == "check"]

    report.resolve_median_ms = round(median(resolve_times), 1)
    report.resolve_p95_ms = round(percentile(resolve_times, 95), 1)
    report.check_median_ms = round(median(check_times), 1)
    report.check_p95_ms = round(percentile(check_times, 95), 1)

    # Scope health
    try:
        from ..engine.discovery import find_all_scopes
        scope_files = find_all_scopes(repo_root)
        report.total_scopes = len(scope_files)
        report.avg_observations = (
            len(observations) / max(len(scope_files), 1)
        )

        # Count scopes with >80% recall
        scope_recalls = _compute_scope_recalls(observations, sessions)
        report.scopes_above_80_recall = sum(
            1 for r in scope_recalls.values() if r >= 0.8
        )

        # Stale scopes
        import time
        now = time.time()
        for sf in scope_files:
            mtime = os.path.getmtime(sf)
            if now - mtime > 30 * 86400:
                report.stale_scopes += 1
    except Exception:
        pass

    return report


def format_bench_report(report: BenchReport) -> str:
    """Format benchmark report for terminal output."""
    lines = []

    lines.append("dotscope bench\n")

    lines.append("  Token Efficiency")
    if report.efficiency_ratio > 0:
        lines.append(f"    Average files resolved: {report.avg_tokens_resolved}")
        lines.append(f"    Average files agent used: {report.avg_tokens_used}")
        lines.append(f"    Efficiency ratio: {report.efficiency_ratio:.1%}")
    else:
        lines.append("    No observation data yet")
    lines.append("")

    lines.append("  Hold Rate")
    lines.append(f"    Total commits observed: {report.total_commits}")
    lines.append(f"    Holds acknowledged (rule was wrong): {report.holds_acknowledged}")
    eff = round(report.effective_hold_rate * 100, 1) if report.effective_hold_rate else 0
    lines.append(f"    Effective hold rate: {eff}%")
    lines.append("")

    lines.append("  Compilation Speed")
    if report.resolve_median_ms > 0:
        lines.append(f"    Median resolve: {report.resolve_median_ms}ms")
        lines.append(f"    P95 resolve: {report.resolve_p95_ms}ms")
    else:
        lines.append("    No timing data yet")
    if report.check_median_ms > 0:
        lines.append(f"    Median check: {report.check_median_ms}ms")
        lines.append(f"    P95 check: {report.check_p95_ms}ms")
    lines.append("")

    lines.append("  Scope Health")
    lines.append(f"    Scopes with >80% recall: {report.scopes_above_80_recall}/{report.total_scopes}")
    lines.append(f"    Stale scopes (>30 days): {report.stale_scopes}")
    lines.append(f"    Avg observations per scope: {report.avg_observations:.1f}")

    return "\n".join(lines)


def _compute_scope_recalls(observations, sessions) -> Dict[str, float]:
    """Compute average recall per scope."""
    scope_recalls: Dict[str, List[float]] = {}
    session_scopes = {s.session_id: s.scope_expr for s in sessions}
    for obs in observations:
        scope = session_scopes.get(obs.session_id, "unknown")
        scope_recalls.setdefault(scope, []).append(obs.recall)
    return {
        scope: sum(recalls) / len(recalls)
        for scope, recalls in scope_recalls.items()
        if recalls
    }
