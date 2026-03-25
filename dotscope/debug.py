"""Context bisection: debug why an agent session produced a bad outcome.

Deterministic. No LLM calls. Bisects files, context sections, and
constraints to identify the root cause.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class BisectionResult:
    """Root cause analysis of a bad agent session."""
    session_id: str
    files_that_mattered: List[str] = field(default_factory=list)
    files_that_didnt_help: List[str] = field(default_factory=list)
    context_sections_relevant: List[str] = field(default_factory=list)
    context_sections_irrelevant: List[str] = field(default_factory=list)
    constraints_honored: List[dict] = field(default_factory=list)
    constraints_violated: List[dict] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    diagnosis: str = ""  # "resolution_gap" | "constraint_gap" | "agent_ignored" | "context_conflict"
    recommendations: List[str] = field(default_factory=list)


def debug_session(
    session_id: str,
    repo_root: str,
) -> Optional[BisectionResult]:
    """Bisect a session to find root cause of bad outcome."""
    session = _load_session(repo_root, session_id)
    observation = _load_observation(repo_root, session_id)

    if not session or not observation:
        return None

    recall = observation.get("recall", 1.0)
    if recall >= 0.8:
        return None  # Nothing to debug

    resolved_files = set(session.get("predicted_files", []))
    actual_files = set(observation.get("actual_files_modified", []))

    # Bisect files
    files_that_mattered = sorted(resolved_files & actual_files)
    files_that_didnt_help = sorted(resolved_files - actual_files)
    missing_files = sorted(actual_files - resolved_files)

    # Bisect context
    context = session.get("context", "")
    sections = _parse_sections(context)
    relevant = []
    irrelevant = []
    for name, text in sections.items():
        if any(f in text or os.path.basename(f) in text for f in actual_files):
            relevant.append(name)
        else:
            irrelevant.append(name)

    # Bisect constraints
    constraints = session.get("constraints_served", [])
    honored = []
    violated = []
    for c in constraints:
        if _constraint_violated(c, observation):
            violated.append(c)
        else:
            honored.append(c)

    # Diagnose
    diagnosis, recommendations = _diagnose(
        missing_files, violated, files_that_didnt_help,
    )

    return BisectionResult(
        session_id=session_id,
        files_that_mattered=files_that_mattered,
        files_that_didnt_help=files_that_didnt_help,
        context_sections_relevant=relevant,
        context_sections_irrelevant=irrelevant,
        constraints_honored=honored,
        constraints_violated=violated,
        missing_files=missing_files,
        diagnosis=diagnosis,
        recommendations=recommendations,
    )


def list_bad_sessions(repo_root: str, limit: int = 10) -> List[dict]:
    """List sessions with low recall for debugging."""
    from .sessions import SessionManager
    mgr = SessionManager(repo_root)
    observations = mgr.get_observations(limit=200)
    sessions = mgr.get_sessions(limit=200)
    session_map = {s.session_id: s for s in sessions}

    bad = []
    for obs in observations:
        if obs.recall < 0.8:
            s = session_map.get(obs.session_id)
            bad.append({
                "session_id": obs.session_id,
                "scope": s.scope_expr if s else "unknown",
                "recall": obs.recall,
                "gaps": obs.touched_not_predicted[:3],
            })

    return bad[:limit]


def format_debug_report(result: BisectionResult) -> str:
    """Format bisection result for terminal output."""
    lines = [f"dotscope debug: session {result.session_id}\n"]

    lines.append("  File Bisection")
    if result.files_that_mattered:
        lines.append(f"    Files that mattered: {', '.join(result.files_that_mattered)}")
    if result.files_that_didnt_help:
        lines.append(f"    Files that didn't help: {', '.join(result.files_that_didnt_help)}")
    if result.missing_files:
        lines.append(f"    Missing files: {', '.join(result.missing_files)}")
    lines.append("")

    if result.context_sections_relevant or result.context_sections_irrelevant:
        lines.append("  Context Bisection")
        for s in result.context_sections_relevant:
            lines.append(f"    Relevant: {s}")
        for s in result.context_sections_irrelevant:
            lines.append(f"    Irrelevant: {s}")
        lines.append("")

    if result.constraints_violated:
        lines.append("  Constraints Violated")
        for c in result.constraints_violated:
            lines.append(f"    {c.get('message', 'unknown')}")
        lines.append("")

    lines.append(f"  Diagnosis: {result.diagnosis}")
    for rec in result.recommendations:
        lines.append(f"    -> {rec}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_session(repo_root: str, session_id: str) -> Optional[dict]:
    """Load a session file."""
    path = os.path.join(repo_root, ".dotscope", "sessions", f"{session_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_observation(repo_root: str, session_id: str) -> Optional[dict]:
    """Find observation matching a session."""
    from .sessions import SessionManager
    mgr = SessionManager(repo_root)
    for obs in mgr.get_observations(limit=200):
        if obs.session_id == session_id:
            return {
                "actual_files_modified": obs.actual_files_modified,
                "recall": obs.recall,
                "touched_not_predicted": obs.touched_not_predicted,
            }
    return None


def _parse_sections(context: str) -> Dict[str, str]:
    """Parse context into named sections (## headers)."""
    sections: Dict[str, str] = {}
    current = "main"
    lines: List[str] = []

    for line in context.splitlines():
        if line.startswith("## "):
            if lines:
                sections[current] = "\n".join(lines)
            current = line[3:].strip()
            lines = []
        else:
            lines.append(line)

    if lines:
        sections[current] = "\n".join(lines)
    return sections


def _constraint_violated(constraint: dict, observation: dict) -> bool:
    """Check if a served constraint was violated in the observation."""
    msg = constraint.get("message", "").lower()
    actual = set(observation.get("actual_files_modified", []))

    # Contract: check if both sides were modified
    if "modify" in msg and "review" in msg:
        for f in actual:
            if f.lower() in msg:
                # One side modified — check if the other was too
                return True  # Simplified: if contract mentioned, check presence

    return False


def _diagnose(
    missing_files: List[str],
    constraints_violated: List[dict],
    files_unused: List[str],
) -> Tuple[str, List[str]]:
    """Determine root cause and recommendations."""
    recommendations = []

    if missing_files:
        for f in missing_files[:3]:
            recommendations.append(f"Add {f} to scope includes or add assertion ensure_includes: [{f}]")
        return "resolution_gap", recommendations

    if constraints_violated and not missing_files:
        for c in constraints_violated:
            recommendations.append(
                f"Agent ignored constraint: {c.get('message', '')[:60]}. "
                f"Consider strengthening to HOLD."
            )
        return "agent_ignored", recommendations

    if not missing_files and not constraints_violated:
        recommendations.append("Add anti-patterns or intent directives for the patterns that caused the bad commit")
        return "constraint_gap", recommendations

    return "context_conflict", ["Review scope context for contradictory guidance"]
