"""Lessons & constraints: machine-generated knowledge from observation patterns.

Lessons are extracted automatically when the observation layer detects
recurring patterns. Constraints are evidence-based invariants derived from
the dependency graph and git history.

Both are injected into resolved context so agents receive them automatically.
"""

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .models import ObservationLog, SessionLog


@dataclass
class Lesson:
    """A machine-generated lesson from observation patterns."""
    trigger: str
    observation: str
    lesson_text: str
    confidence: float
    created: float
    source_sessions: List[str] = field(default_factory=list)
    acknowledged: bool = False


@dataclass
class ObservedInvariant:
    """An evidence-based boundary constraint."""
    boundary: str          # e.g., "auth -> payments"
    direction: str         # "no_import"
    held_since: str        # ISO date
    commit_count: int
    confidence: float
    violations: List[str] = field(default_factory=list)


def generate_lessons(
    sessions: List[SessionLog],
    observations: List[ObservationLog],
    module: Optional[str] = None,
) -> List[Lesson]:
    """Generate lessons from observation patterns.

    Patterns detected:
    - File resolved but never touched (noise candidate)
    - File touched but not in scope (scope gap)
    - Scope consistently low recall for certain task keywords
    """
    lessons = []
    obs_by_session = {obs.session_id: obs for obs in observations}

    # Track per-file stats
    file_resolved: Dict[str, int] = defaultdict(int)
    file_touched: Dict[str, int] = defaultdict(int)
    file_gap: Dict[str, int] = defaultdict(int)  # touched but not predicted

    for session in sessions:
        if module and module not in session.scope_expr:
            continue

        obs = obs_by_session.get(session.session_id)
        if not obs:
            continue

        for f in session.predicted_files:
            file_resolved[f] += 1
        for f in obs.actual_files_modified:
            file_touched[f] += 1
        for f in obs.touched_not_predicted:
            file_gap[f] += 1

    # Lesson: file resolved but never touched in 10+ observations
    total_obs = len([s for s in sessions if s.session_id in obs_by_session])
    for f, count in file_resolved.items():
        if count >= 10 and file_touched.get(f, 0) == 0:
            lessons.append(Lesson(
                trigger="resolved_never_touched",
                observation=f"Resolved {count} times, modified 0 times",
                lesson_text=(
                    f"{os.path.basename(f)} is consistently included but never modified. "
                    f"Consider reducing its budget priority."
                ),
                confidence=min(count / 20, 1.0),
                created=time.time(),
            ))

    # Lesson: file touched but not in scope in 5+ observations
    for f, count in file_gap.items():
        if count >= 3:
            lessons.append(Lesson(
                trigger="touched_not_predicted",
                observation=f"Modified in {count} commits but not in scope includes",
                lesson_text=(
                    f"{os.path.basename(f)} is frequently needed but missing from scope. "
                    f"Consider adding to includes."
                ),
                confidence=min(count / 10, 1.0),
                created=time.time(),
            ))

    # Lesson: most frequently modified file
    if file_touched and total_obs >= 5:
        top_file = max(file_touched, key=file_touched.get)
        top_count = file_touched[top_file]
        if top_count >= 3:
            ratio = top_count / total_obs
            lessons.append(Lesson(
                trigger="hotspot",
                observation=f"Modified in {top_count}/{total_obs} observations ({ratio:.0%})",
                lesson_text=(
                    f"{os.path.basename(top_file)} is the most frequently modified file "
                    f"(touched in {ratio:.0%} of sessions)."
                ),
                confidence=ratio,
                created=time.time(),
            ))

    return sorted(lessons, key=lambda ls: -ls.confidence)


def detect_invariants(
    graph_edges: List[tuple],
    module: str,
    all_modules: List[str],
    commit_count: int = 0,
) -> List[ObservedInvariant]:
    """Detect boundary invariants from the dependency graph.

    If module A has never imported from module B across the entire history,
    that's an observed invariant.
    """
    # Which modules does this module import from?
    imports_from = set()
    for src, dst in graph_edges:
        src_parts = src.split("/")
        dst_parts = dst.split("/")
        if len(src_parts) > 1 and src_parts[0] == module:
            if len(dst_parts) > 1 and dst_parts[0] != module:
                imports_from.add(dst_parts[0])

    invariants = []
    for other in all_modules:
        if other == module:
            continue
        if other not in imports_from:
            confidence = min(commit_count / 100, 1.0) if commit_count > 0 else 0.5
            invariants.append(ObservedInvariant(
                boundary=f"{module} -> {other}",
                direction="no_import",
                held_since="",  # Would need git history to determine
                commit_count=commit_count,
                confidence=round(confidence, 2),
            ))

    return invariants


def format_lessons_for_context(lessons: List[Lesson], invariants: List[ObservedInvariant]) -> str:
    """Format lessons and invariants for injection into resolved context."""
    parts = []

    if lessons:
        parts.append("## Lessons (from observed sessions)")
        for lesson in lessons[:5]:
            parts.append(f"- {lesson.lesson_text}")

    if invariants:
        high_conf = [inv for inv in invariants if inv.confidence >= 0.9]
        if high_conf:
            parts.append("## Boundaries")
            for inv in high_conf[:5]:
                parts.append(
                    f"- {inv.boundary}: no imports observed "
                    f"({inv.commit_count} commits). Do not break."
                )

    return "\n".join(parts)


def save_lessons(dot_dir: Path, module: str, lessons: List[Lesson]) -> None:
    """Save lessons to .dotscope/lessons/<module>.json."""
    lessons_dir = dot_dir / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "trigger": item.trigger,
            "observation": item.observation,
            "lesson_text": item.lesson_text,
            "confidence": item.confidence,
            "created": item.created,
            "source_sessions": item.source_sessions,
            "acknowledged": item.acknowledged,
        }
        for item in lessons
    ]
    (lessons_dir / f"{module}.json").write_text(json.dumps(data, indent=2))


def load_lessons(dot_dir: Path, module: str) -> List[Lesson]:
    """Load lessons from .dotscope/lessons/<module>.json."""
    path = dot_dir / "lessons" / f"{module}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [Lesson(**item) for item in data]
    except (json.JSONDecodeError, TypeError):
        return []


def save_invariants(dot_dir: Path, module: str, invariants: List[ObservedInvariant]) -> None:
    """Save invariants to .dotscope/invariants/<module>.json."""
    inv_dir = dot_dir / "invariants"
    inv_dir.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "boundary": inv.boundary,
            "direction": inv.direction,
            "held_since": inv.held_since,
            "commit_count": inv.commit_count,
            "confidence": inv.confidence,
            "violations": inv.violations,
        }
        for inv in invariants
    ]
    (inv_dir / f"{module}.json").write_text(json.dumps(data, indent=2))


def load_invariants(dot_dir: Path, module: str) -> List[ObservedInvariant]:
    """Load invariants from .dotscope/invariants/<module>.json."""
    path = dot_dir / "invariants" / f"{module}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [ObservedInvariant(**item) for item in data]
    except (json.JSONDecodeError, TypeError):
        return []
