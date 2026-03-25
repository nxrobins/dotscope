"""DX Visibility: making dotscope's value legible at point of use.

Five features that surface existing data through two channels:
1. Session Summary — aggregate stats for the MCP session
2. Attribution Hints — top context fragments + provenance
3. Post-Commit Delta — per-scope accuracy after observe
4. Health Nudges — warnings when scope accuracy degrades
5. Near-Miss Detection — disasters that didn't happen
"""

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import ObservationLog, SessionLog


# ---------------------------------------------------------------------------
# Feature 1: Session Summary
# ---------------------------------------------------------------------------


@dataclass
class SessionTracker:
    """Accumulates stats across MCP tool calls within a session."""

    scopes_resolved: int = 0
    tokens_served: int = 0
    tokens_available: int = 0
    context_fields_used: int = 0
    implicit_contracts_applied: int = 0
    _start_time: float = field(default_factory=time.time)

    def record_resolve(
        self,
        token_count: int,
        total_repo_tokens: int,
        context_has_contracts: bool,
    ) -> None:
        self.scopes_resolved += 1
        self.tokens_served += token_count
        if total_repo_tokens > self.tokens_available:
            self.tokens_available = total_repo_tokens
        if context_has_contracts:
            self.implicit_contracts_applied += 1
        self.context_fields_used += 1

    def summary(self) -> dict:
        reduction = 0
        if self.tokens_available > 0:
            reduction = round(
                (1 - self.tokens_served / max(self.tokens_available, 1)) * 100
            )
        return {
            "scopes_resolved": self.scopes_resolved,
            "tokens_served": self.tokens_served,
            "tokens_available": self.tokens_available,
            "reduction_pct": max(reduction, 0),
            "context_fields_used": self.context_fields_used,
            "implicit_contracts_applied": self.implicit_contracts_applied,
            "observations_pending": self.scopes_resolved > 0,
        }

    def format_terminal(self) -> str:
        """Compact one-liner for stderr."""
        if self.scopes_resolved == 0:
            return ""
        s = self.summary()
        lines = [
            "-- dotscope session " + "-" * 34,
            f"  {s['scopes_resolved']} scopes resolved"
            f" · {s['tokens_served']:,} tokens served"
            f" ({s['reduction_pct']}% reduction)",
            f"  {s['context_fields_used']} context fields referenced"
            f" · {s['implicit_contracts_applied']} implicit contract(s) applied",
            "  Session tracked -> run `dotscope sessions` to review",
            "-" * 55,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 2: Attribution Hints
# ---------------------------------------------------------------------------

# Keywords that signal high-value context lines
_HINT_KEYWORDS = re.compile(
    r"\b(never|always|gotcha|fragile|important|careful|avoid|don't|do not|invariant|hack|warning)\b",
    re.IGNORECASE,
)


def extract_attribution_hints(context: str, max_hints: int = 3) -> List[str]:
    """Extract the highest-value context fragments as standalone statements."""
    if not context:
        return []

    hints = []
    for line in context.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("dotscope-session"):
            continue
        if _HINT_KEYWORDS.search(line):
            # Clean up markdown list markers
            clean = re.sub(r"^[-*]\s+", "", line)
            if len(clean) > 15:  # Skip trivially short matches
                hints.append(clean)

    # Also include any implicit contract lines
    for line in context.split("\n"):
        line = line.strip()
        if "co-change" in line.lower() or "implicit contract" in line.lower():
            clean = re.sub(r"^[-*]\s+", "", line)
            if clean not in hints and len(clean) > 15:
                hints.append(clean)

    return hints[:max_hints]


def compute_source_signals(context: str) -> Dict[str, int]:
    """Count provenance signals in scope context."""
    signals = {
        "from_git_history": 0,
        "from_docstrings": 0,
        "from_signal_comments": 0,
        "from_implicit_contracts": 0,
        "hand_authored": 0,
    }

    for line in context.split("\n"):
        lower = line.lower().strip()
        if "from git history" in lower or "co-change" in lower or "commits" in lower:
            signals["from_git_history"] += 1
        elif "implicit contract" in lower:
            signals["from_implicit_contracts"] += 1
        elif "docstring" in lower or "api:" in lower:
            signals["from_docstrings"] += 1
        elif any(kw in lower for kw in ("invariant:", "hack:", "warning:", "note:")):
            signals["from_signal_comments"] += 1
        elif line.strip() and not line.strip().startswith("#"):
            signals["hand_authored"] += 1

    # Don't return all zeros — filter to non-zero
    return {k: v for k, v in signals.items() if v > 0} or {"hand_authored": 1}


# ---------------------------------------------------------------------------
# Feature 3: Post-Commit Delta
# ---------------------------------------------------------------------------


def format_observation_delta(
    observation: ObservationLog,
    scope_expr: str,
) -> str:
    """Format a post-commit observation as a human-readable delta."""
    lines = []
    scope_name = scope_expr.split("+")[0].split("-")[0].split("@")[0]

    actual_count = len(observation.actual_files_modified)
    predicted_correct = actual_count - len(observation.touched_not_predicted)

    lines.append(f"dotscope: observation recorded for {scope_name}/")

    pct = observation.recall
    suffix = ""
    if pct < 0.6:
        suffix = " <- degraded"
    elif pct >= 0.95:
        suffix = ""

    lines.append(
        f"  {scope_name}/ predicted {predicted_correct}/{actual_count}"
        f" files correctly ({pct:.0%}){suffix}"
    )

    if observation.touched_not_predicted:
        missing = ", ".join(observation.touched_not_predicted[:5])
        lines.append(f"  Missing: {missing}")
        if pct < 0.6:
            lines.append(f"  Run `dotscope health {scope_name}` to diagnose")

    lines.append("  Learning applied -> utility scores updated")
    return "\n".join(lines)


def build_recent_learning(
    observations: List[ObservationLog],
    scope: str,
) -> Optional[dict]:
    """Build recent_learning metadata from observations within 24h."""
    now = time.time()
    day_ago = now - 86400

    recent = [o for o in observations if o.timestamp > day_ago]
    if not recent:
        return None

    latest = recent[-1]
    recalls = [o.recall for o in recent]
    avg = sum(recalls) / len(recalls) if recalls else 0

    # Trend: compare last 3 to previous
    if len(recalls) >= 4:
        recent_avg = sum(recalls[-3:]) / 3
        older_avg = sum(recalls[:-3]) / len(recalls[:-3])
        trend = "improving" if recent_avg > older_avg + 0.05 else "stable"
    else:
        trend = "stable"

    hours_ago = max(1, int((now - latest.timestamp) / 3600))
    result = {
        "last_observation": f"{hours_ago}h ago",
        "accuracy_trend": trend,
        "recent_accuracy": round(avg, 2),
    }

    # Note about what was learned
    if latest.touched_not_predicted:
        result["note"] = (
            f"Added {', '.join(latest.touched_not_predicted[:3])} "
            f"after missed prediction in last commit"
        )

    return result


# ---------------------------------------------------------------------------
# Feature 4: Health Nudges
# ---------------------------------------------------------------------------


def check_health_nudges(
    observations: List[ObservationLog],
    scope: str,
    threshold_drop: float = 0.15,
) -> List[dict]:
    """Generate health warnings when scope accuracy degrades."""
    if len(observations) < 3:
        return []

    warnings = []
    recalls = [o.recall for o in observations]

    # Split into halves
    mid = len(recalls) // 2
    if mid < 1:
        return []

    older_avg = sum(recalls[:mid]) / mid
    recent_avg = sum(recalls[mid:]) / len(recalls[mid:])

    if older_avg - recent_avg >= threshold_drop:
        warnings.append({
            "scope": scope,
            "issue": "accuracy_degraded",
            "current_accuracy": round(recent_avg, 2),
            "previous_accuracy": round(older_avg, 2),
            "suggestion": f"Re-run ingest on {scope}/ to incorporate recent changes",
        })

    return warnings


# ---------------------------------------------------------------------------
# Feature 5: Near-Miss Detection
# ---------------------------------------------------------------------------

# Patterns: (anti_pattern_keywords, safe_pattern_keywords)
_NEAR_MISS_PATTERNS = [
    # Soft delete pattern
    (
        [".delete()", "hard delete", "drop table"],
        [".deactivate()", "soft_delete", "is_active", "deleted_at"],
    ),
    # Direct DB access
    (
        ["raw sql", "execute(", "cursor.execute"],
        ["orm", "query.", "filter(", "objects."],
    ),
    # Force push
    (
        ["--force", "push -f", "reset --hard"],
        ["--force-with-lease", "revert"],
    ),
]


def detect_near_misses(
    context: str,
    diff_text: str,
    scope: str,
) -> List[dict]:
    """Detect cases where scope context may have prevented a mistake.

    A near-miss is when:
    1. The context contains a warning about an anti-pattern
    2. The diff does NOT contain the anti-pattern
    3. The diff DOES contain the safe alternative

    False positives are acceptable — they still build trust.
    """
    if not context or not diff_text:
        return []

    near_misses = []
    context_lower = context.lower()
    diff_lower = diff_text.lower()

    # Check keyword patterns from context
    for anti_keywords, safe_keywords in _NEAR_MISS_PATTERNS:
        # Is the anti-pattern warned about in context?
        context_warns = any(kw in context_lower for kw in anti_keywords)
        if not context_warns:
            continue

        # Anti-pattern absent from diff, safe pattern present?
        anti_in_diff = any(kw in diff_lower for kw in anti_keywords)
        safe_in_diff = any(kw in diff_lower for kw in safe_keywords)

        if not anti_in_diff and safe_in_diff:
            # Find the specific context line that warned
            warning_line = ""
            for line in context.split("\n"):
                if any(kw in line.lower() for kw in anti_keywords + safe_keywords):
                    warning_line = line.strip()
                    break

            near_misses.append({
                "scope_context_used": warning_line or "Context warning applied",
                "potential_impact": f"Avoided anti-pattern in {scope}/",
            })

    # Also check explicit "never"/"don't" patterns from context
    for line in context.split("\n"):
        line_clean = line.strip()
        if not line_clean:
            continue

        match = re.search(
            r"\b(never|don't|do not|avoid)\b\s+(.{10,50})",
            line_clean,
            re.IGNORECASE,
        )
        if not match:
            continue

        anti_phrase = match.group(2).lower().split(".")[0].strip()
        # If the anti-phrase is NOT in the diff, that's a candidate
        if anti_phrase not in diff_lower and len(anti_phrase) > 5:
            near_misses.append({
                "scope_context_used": line_clean,
                "potential_impact": f"Anti-pattern avoided: {anti_phrase}",
            })

    # Deduplicate by scope_context_used
    seen = set()
    unique = []
    for nm in near_misses:
        key = nm["scope_context_used"]
        if key not in seen:
            seen.add(key)
            unique.append(nm)

    return unique[:3]  # Cap at 3
