"""Baseline vs candidate comparison with per-metric deltas."""

import math
from dataclasses import dataclass, field
from typing import Dict, List

from ..models.eval import EvalRun


@dataclass
class MetricDelta:
    """Delta between baseline and candidate for a single metric."""
    name: str
    baseline: float
    candidate: float
    delta: float
    improved: bool
    significant: bool  # |delta| > threshold


@dataclass
class ComparisonReport:
    """Full comparison between two eval runs."""
    baseline_id: str
    candidate_id: str
    fitness_delta: float
    gate_changes: List[str] = field(default_factory=list)
    primary_deltas: List[MetricDelta] = field(default_factory=list)
    secondary_deltas: List[MetricDelta] = field(default_factory=list)
    verdict: str = ""  # "better", "worse", "equivalent"


# Significance thresholds for declaring a metric changed meaningfully
PRIMARY_SIGNIFICANCE = 0.02
SECONDARY_SIGNIFICANCE = 0.05


def compare_runs(baseline: EvalRun, candidate: EvalRun) -> ComparisonReport:
    """Compare two eval runs and produce a detailed delta report."""
    report = ComparisonReport(
        baseline_id=baseline.candidate_id,
        candidate_id=candidate.candidate_id,
        fitness_delta=round(candidate.fitness - baseline.fitness, 4),
    )

    # Gate changes
    base_gates = {g.name: g for g in baseline.gates}
    cand_gates = {g.name: g for g in candidate.gates}
    for name in sorted(set(list(base_gates.keys()) + list(cand_gates.keys()))):
        bg = base_gates.get(name)
        cg = cand_gates.get(name)
        if bg and cg and bg.passed != cg.passed:
            direction = "FIXED" if cg.passed else "BROKEN"
            report.gate_changes.append(f"{name}: {direction}")

    # Primary deltas
    if baseline.primary and candidate.primary:
        bp = baseline.primary
        cp = candidate.primary
        for attr, label in [
            ("mean_f1", "edit_frontier_f1"),
            ("mean_recall", "touched_file_recall"),
            ("mean_precision", "touched_file_precision"),
            ("invariant_recall", "invariant_recall"),
            ("test_precision", "test_precision"),
            ("freshness_accuracy", "freshness_accuracy"),
        ]:
            bv = getattr(bp, attr)
            cv = getattr(cp, attr)
            delta = round(cv - bv, 4)
            report.primary_deltas.append(MetricDelta(
                name=label,
                baseline=bv,
                candidate=cv,
                delta=delta,
                improved=delta > 0,
                significant=abs(delta) >= PRIMARY_SIGNIFICANCE,
            ))

    # Secondary deltas
    if baseline.secondary and candidate.secondary:
        bs = baseline.secondary
        cs = candidate.secondary
        for attr, label in [
            ("task_success", "first_pass_task_success"),
            ("test_pass_rate", "first_pass_test_pass_rate"),
            ("scope_expansions", "scope_expansion_rate"),
            ("irrelevant_files", "irrelevant_file_rate"),
            ("token_cost", "token_cost"),
            ("override_rate", "human_override_rate"),
            ("false_warning_rate", "false_warning_rate"),
        ]:
            bv = getattr(bs, attr)
            cv = getattr(cs, attr)
            delta = round(cv - bv, 4)
            report.secondary_deltas.append(MetricDelta(
                name=label,
                baseline=bv,
                candidate=cv,
                delta=delta,
                improved=delta > 0,
                significant=abs(delta) >= SECONDARY_SIGNIFICANCE,
            ))

    # Verdict
    if report.fitness_delta > PRIMARY_SIGNIFICANCE:
        report.verdict = "better"
    elif report.fitness_delta < -PRIMARY_SIGNIFICANCE:
        report.verdict = "worse"
    else:
        report.verdict = "equivalent"

    return report


def format_comparison(report: ComparisonReport) -> str:
    """Format comparison report for terminal output."""
    lines = [
        f"Eval comparison: {report.baseline_id} vs {report.candidate_id}",
        f"Verdict: {report.verdict.upper()} (fitness delta: {report.fitness_delta:+.4f})",
        "",
    ]

    if report.gate_changes:
        lines.append("Gate changes:")
        for change in report.gate_changes:
            lines.append(f"  {change}")
        lines.append("")

    lines.append("Primary metrics (edit frontier):")
    for d in report.primary_deltas:
        marker = "+" if d.improved else "-" if d.delta < 0 else " "
        sig = "*" if d.significant else " "
        lines.append(
            f"  {sig}{marker} {d.name}: {d.baseline:.3f} -> {d.candidate:.3f} ({d.delta:+.4f})"
        )
    lines.append("")

    lines.append("Secondary metrics (downstream):")
    for d in report.secondary_deltas:
        marker = "+" if d.improved else "-" if d.delta < 0 else " "
        sig = "*" if d.significant else " "
        lines.append(
            f"  {sig}{marker} {d.name}: {d.baseline:.3f} -> {d.candidate:.3f} ({d.delta:+.4f})"
        )

    return "\n".join(lines)
