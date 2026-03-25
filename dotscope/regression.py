"""Observation regression suite: freeze successful sessions as test cases.

When dotscope's internals change, replay frozen sessions to verify the new
version resolves the same or better context.
"""

import hashlib
import json
import os
from dataclasses import asdict
from typing import List, Optional
from uuid import uuid4

from .models.state import RegressionCase, ReplayResult  # noqa: F401


def maybe_freeze_session(
    observation: object,
    session: object,
    repo_root: str,
    min_recall: float = 0.8,
) -> Optional[str]:
    """Freeze a successful session as a regression test case.

    Returns the case ID if frozen, None otherwise.
    """
    recall = getattr(observation, "recall", 0.0)
    if recall < min_recall:
        return None

    predicted = getattr(session, "predicted_files", [])
    context_hash = getattr(session, "context_hash", "")
    scope_expr = getattr(session, "scope_expr", "")

    case = RegressionCase(
        id=f"regression_{uuid4().hex[:8]}",
        scope_expr=scope_expr,
        expected_files=list(predicted),
        expected_context_hash=context_hash,
        actual_recall=recall,
        timestamp=getattr(observation, "timestamp", ""),
    )

    reg_dir = os.path.join(repo_root, ".dotscope", "regressions")
    os.makedirs(reg_dir, exist_ok=True)

    path = os.path.join(reg_dir, f"{case.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(case), f, indent=2)

    return case.id


def load_regressions(repo_root: str) -> List[RegressionCase]:
    """Load all frozen regression cases."""
    reg_dir = os.path.join(repo_root, ".dotscope", "regressions")
    if not os.path.isdir(reg_dir):
        return []

    cases = []
    for fname in sorted(os.listdir(reg_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(reg_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            cases.append(RegressionCase(
                id=d["id"],
                scope_expr=d.get("scope_expr", ""),
                budget=d.get("budget"),
                task=d.get("task"),
                expected_files=d.get("expected_files", []),
                expected_context_hash=d.get("expected_context_hash", ""),
                actual_recall=d.get("actual_recall", 0.0),
                timestamp=d.get("timestamp", ""),
            ))
        except (json.JSONDecodeError, KeyError, IOError):
            continue

    return cases


def replay_regression(
    case: RegressionCase,
    repo_root: str,
) -> ReplayResult:
    """Replay a frozen session against current codebase state."""
    from .composer import compose
    from .budget import apply_budget

    resolved = compose(case.scope_expr, root=repo_root, follow_related=True)
    if case.budget:
        resolved = apply_budget(resolved, case.budget)

    new_files = set(resolved.files)
    expected = set(case.expected_files)

    new_hash = hashlib.sha256(resolved.context.encode()).hexdigest()[:16]

    return ReplayResult(
        case=case,
        new_files=sorted(new_files),
        new_context_hash=new_hash,
        files_added=sorted(new_files - expected),
        files_dropped=sorted(expected - new_files),
        context_changed=(new_hash != case.expected_context_hash),
        is_regression=len(expected - new_files) > 0,
    )


def format_replay_report(results: List[ReplayResult]) -> str:
    """Format replay results for terminal output."""
    if not results:
        return "No regression cases found. Sessions are auto-frozen after successful observations."

    lines = [f"dotscope test-compiler: replaying {len(results)} historical sessions\n"]
    passed = 0
    regressions = 0

    for r in results:
        prefix = f"  {r.case.id}  {r.case.scope_expr}"
        if r.case.budget:
            prefix += f" (budget {r.case.budget})"

        if not r.is_regression and not r.files_added:
            lines.append(f"{prefix}")
            lines.append(f"    Files: {len(r.new_files)}/{len(r.case.expected_files)} same  OK")
            passed += 1
        elif not r.is_regression and r.files_added:
            lines.append(f"{prefix}")
            added = ", ".join(r.files_added[:3])
            lines.append(f"    Files: +{len(r.files_added)} added ({added})  OK (improvement)")
            passed += 1
        else:
            lines.append(f"{prefix}")
            dropped = ", ".join(r.files_dropped[:3])
            lines.append(f"    REGRESSION: {dropped} no longer resolved")
            regressions += 1

        if r.context_changed:
            lines.append(f"    Context hash: changed")

        lines.append("")

    lines.append(f"  {passed}/{len(results)} passed, {regressions} regression(s) detected")
    return "\n".join(lines)
