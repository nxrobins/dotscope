"""DX Visibility: making dotscope's value legible at point of use.

Five features that surface existing data through two channels:
1. Session Summary — aggregate stats for the MCP session
2. Attribution Hints — top context fragments + provenance
3. Post-Commit Delta — per-scope accuracy after observe
4. Health Nudges — warnings when scope accuracy degrades
5. Near-Miss Detection — disasters that didn't happen
"""

import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .models.state import ObservationLog, SessionLog, SessionStats  # noqa: F401
from .paths import normalize_relative_path


class SessionTracker:
    """Accumulates stats across MCP tool calls within a session."""

    def __init__(self) -> None:
        self._stats = SessionStats()

    def record_resolve(self, scope_name: str, response: dict) -> None:
        """Called after every resolve_scope response is built."""
        now = datetime.now(timezone.utc).isoformat()
        if not self._stats.started_at:
            self._stats.started_at = now
        self._stats.last_activity = now

        self._stats.scopes_resolved += 1
        self._stats.unique_scopes.add(scope_name)
        self._stats.tokens_served += response.get("token_count", 0)
        self._stats.tokens_available = max(
            self._stats.tokens_available,
            response.get("_repo_tokens", 0),
        )

        hints = response.get("attribution_hints", [])
        self._stats.attribution_hints_served += len(hints)

        if response.get("context"):
            self._stats.context_fields_used += 1

        warnings = response.get("health_warnings", [])
        self._stats.health_warnings_surfaced += len(warnings)

        constraints = response.get("constraints", [])
        self._stats.constraints_served.extend(constraints)

    def set_repo_root(self, root: str) -> None:
        """Set repo root for counterfactual computation."""
        self._repo_root = root

    def summary(self) -> dict:
        """Return session summary as dict for MCP response."""
        s = self._stats
        reduction_pct = 0.0
        if s.tokens_available > 0:
            reduction_pct = round(
                (1 - s.tokens_served / s.tokens_available) * 100, 1
            )
        result = {
            "scopes_resolved": s.scopes_resolved,
            "unique_scopes": len(s.unique_scopes),
            "tokens_served": s.tokens_served,
            "tokens_available": s.tokens_available,
            "reduction_pct": max(reduction_pct, 0.0),
            "attribution_hints_served": s.attribution_hints_served,
            "health_warnings_surfaced": s.health_warnings_surfaced,
            "started_at": s.started_at,
            "last_activity": s.last_activity,
        }

        # Counterfactuals (gated by onboarding stage)
        cfs = self._compute_counterfactuals()
        if cfs:
            result["counterfactuals"] = [
                {
                    "type": cf.type,
                    "description": cf.description,
                    "source": cf.source,
                    "severity": cf.severity,
                }
                for cf in cfs
            ]

        return result

    def format_terminal(self) -> str:
        """Format summary for stderr output."""
        s = self._stats
        if s.scopes_resolved == 0:
            return ""

        reduction_pct = 0
        if s.tokens_available > 0:
            reduction_pct = round(
                (1 - s.tokens_served / s.tokens_available) * 100
            )

        scope_word = "scope" if s.scopes_resolved == 1 else "scopes"
        lines = [
            "-- dotscope session " + "-" * 34,
            f"  {s.scopes_resolved} {scope_word} resolved"
            f" . {s.tokens_served:,} tokens served"
            f" ({reduction_pct}% reduction)",
        ]

        # Counterfactuals (the magic section)
        cfs = self._compute_counterfactuals()
        if cfs:
            from .counterfactual import format_counterfactuals_terminal
            cf_text = format_counterfactuals_terminal(cfs)
            if cf_text:
                lines.append(cf_text)

        # Knowledge provided
        provided = []
        if s.attribution_hints_served:
            provided.append(f"{s.attribution_hints_served} attribution hints served")
        if s.health_warnings_surfaced:
            provided.append(f"{s.health_warnings_surfaced} health warnings surfaced")
        if s.constraints_served:
            provided.append(f"{len(s.constraints_served)} constraints applied")
        if provided:
            lines.append("")
            lines.append("  What dotscope provided:")
            for p in provided:
                lines.append(f"    {p}")

        # Milestone message
        try:
            root = getattr(self, "_repo_root", None)
            if root:
                from .onboarding import load_onboarding, milestone_message, next_step
                state = load_onboarding(root)
                msg = milestone_message(state)
                if msg:
                    lines.append(f"\n  {msg}")
                ns = next_step(state)
                if ns:
                    lines.append(f"\n  {ns}")
        except Exception:
            pass

        lines.append("-" * 55)
        return "\n".join(lines)

    def _compute_counterfactuals(self) -> list:
        """Compute counterfactuals from session data. Best-effort."""
        try:
            root = getattr(self, "_repo_root", None)
            if not root:
                return []

            from .onboarding import load_onboarding, should_show_counterfactuals
            state = load_onboarding(root)
            if not should_show_counterfactuals(state):
                return []

            from .counterfactual import compute_counterfactuals
            from .near_miss import load_recent_near_misses
            import json

            # Gather data
            near_misses = []
            for scope in self._stats.unique_scopes:
                nms = load_recent_near_misses(root, scope)
                near_misses.extend(nms)

            invariants = {}
            inv_path = os.path.join(root, ".dotscope", "invariants.json")
            if os.path.exists(inv_path):
                with open(inv_path, "r", encoding="utf-8") as f:
                    invariants = json.load(f)

            intents = []
            try:
                from .intent import load_intents
                intents = load_intents(root)
            except Exception:
                pass

            # Modified files from recent observations
            modified = set()
            diff_text = ""
            try:
                from .sessions import SessionManager
                mgr = SessionManager(root)
                recent_obs = mgr.get_observations(limit=5)
                for obs in recent_obs:
                    modified.update(obs.actual_files_modified)
            except Exception:
                pass

            return compute_counterfactuals(
                constraints_served=self._stats.constraints_served,
                modified_files=modified,
                diff_text=diff_text,
                near_misses=near_misses,
                invariants=invariants,
                intents=intents,
            )
        except Exception:
            return []

    def reset(self) -> None:
        """Clear all session stats."""
        self._stats = SessionStats()


# ---------------------------------------------------------------------------
# Feature 2: Attribution Hints
# ---------------------------------------------------------------------------

# Keywords that signal high-value context lines
_HINT_KEYWORDS = re.compile(
    r"\b(never|always|gotcha|fragile|important|careful|avoid|don't|do not|invariant|hack|warning)\b",
    re.IGNORECASE,
)


def extract_attribution_hints(
    context: str,
    max_hints: int = 3,
    implicit_contracts: Optional[List] = None,
    graph_hubs: Optional[Dict] = None,
    scope_directory: str = "",
) -> List[Dict[str, str]]:
    """Extract highest-value context fragments with provenance.

    Sources (in priority order):
    1. Implicit contracts from cached history → source: git_history
    2. Warning-keyword lines from context → source inferred from section headers
    3. Graph hub info → source: graph

    Returns: [{"hint": "...", "source": "git_history|hand_authored|..."}]
    """
    hints: List[Dict[str, str]] = []
    seen: set = set()

    # 1. Implicit contracts (highest priority — things nobody documented)
    if implicit_contracts:
        for ic in implicit_contracts:
            desc = getattr(ic, "description", "") or str(ic.get("description", "")) if isinstance(ic, dict) else ic.description
            trigger = getattr(ic, "trigger_file", "") if not isinstance(ic, dict) else ic.get("trigger_file", "")
            coupled = getattr(ic, "coupled_file", "") if not isinstance(ic, dict) else ic.get("coupled_file", "")

            if scope_directory and not (
                trigger.startswith(scope_directory + "/")
                or coupled.startswith(scope_directory + "/")
            ):
                continue

            if desc and desc not in seen and len(desc) > 15:
                hints.append({"hint": desc, "source": "git_history"})
                seen.add(desc)

    # 2. Warning-keyword lines from context
    if context:
        for line in context.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("dotscope-session"):
                continue

            clean = re.sub(r"^[-*]\s+", "", line)
            if len(clean) <= 15 or clean in seen:
                continue

            if _HINT_KEYWORDS.search(line):
                source = _infer_source(line, context)
                hints.append({"hint": clean, "source": source})
                seen.add(clean)
            elif "co-change" in line.lower():
                hints.append({"hint": clean, "source": "git_history"})
                seen.add(clean)

    # 3. Graph hubs (wide blast radius warnings)
    if graph_hubs and scope_directory:
        for path, hub_info in graph_hubs.items():
            if not path.startswith(scope_directory + "/"):
                continue
            count = hub_info.get("imported_by_count", 0)
            if count >= 5:
                hint = f"{path} is imported by {count} files, changes here have wide blast radius"
                if hint not in seen:
                    hints.append({"hint": hint, "source": "graph"})
                    seen.add(hint)

    # Priority sort: git_history > signal_comment > hand_authored > docstring > graph
    _PRIORITY = {
        "git_history": 0, "implicit_contract": 0,
        "signal_comment": 1, "hand_authored": 2,
        "docstring": 3, "graph": 4,
    }
    hints.sort(key=lambda h: _PRIORITY.get(h["source"], 5))

    return hints[:max_hints]


def _infer_source(line: str, full_context: str) -> str:
    """Infer provenance by walking backward to the nearest ## section header."""
    lines = full_context.splitlines()
    target_idx = None
    for i, l in enumerate(lines):
        if l.strip() == line.strip():
            target_idx = i
            break

    if target_idx is None:
        return _classify_line(line)

    for i in range(target_idx, -1, -1):
        header = lines[i].strip().lower()
        if not header.startswith("##"):
            continue
        if "implicit contract" in header or "git history" in header:
            return "git_history"
        if "stability" in header:
            return "git_history"
        if "docstring" in header or "readme" in header:
            return "docstring"
        if "signal" in header or "comment" in header:
            return "signal_comment"
        # Any other ## header — treat content as hand_authored
        return "hand_authored"

    return _classify_line(line)


def _classify_line(line: str) -> str:
    """Fallback: classify a line's provenance from its own content."""
    lower = line.lower()
    if "co-change" in lower or "from git history" in lower or "commits" in lower:
        return "git_history"
    if "implicit contract" in lower:
        return "git_history"
    if any(kw in lower for kw in ("invariant:", "hack:", "warning:", "note:")):
        return "signal_comment"
    return "hand_authored"


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
    if pct < 0.7:
        suffix = " <- degraded"

    lines.append(
        f"  {scope_name}/ predicted {predicted_correct}/{actual_count}"
        f" files correctly ({pct:.0%}){suffix}"
    )

    if observation.touched_not_predicted:
        missing_names = [
            os.path.basename(f) for f in observation.touched_not_predicted[:4]
        ]
        if len(observation.touched_not_predicted) > 4:
            missing_names.append(
                f"+{len(observation.touched_not_predicted) - 4} more"
            )
        lines.append(f"  Missing: {', '.join(missing_names)}")
        if pct < 0.8:
            lines.append(f"  Run `dotscope health {scope_name}` to diagnose")

    lines.append("  Utility scores updated")
    return "\n".join(lines)


def build_accuracy(
    observations: List[ObservationLog],
    scope: str,
) -> Optional[dict]:
    """Build unified accuracy metadata from all observations.

    Merges what was previously scope_accuracy + recent_learning into one field.
    Returns None if no observations exist.
    """
    if not observations:
        return None

    now = time.time()
    recalls = [o.recall for o in observations]
    precisions = [o.precision for o in observations]
    avg_recall = sum(recalls) / len(recalls)
    avg_precision = sum(precisions) / len(precisions)

    # Trend: compare recent vs older
    recent_r = recalls[-5:] if len(recalls) >= 5 else recalls
    older_r = recalls[:-5] if len(recalls) > 5 else []
    trend = (
        "improving"
        if older_r and sum(recent_r) / len(recent_r) > sum(older_r) / len(older_r)
        else "stable"
    )

    result: dict = {
        "observations": len(observations),
        "avg_recall": round(avg_recall, 3),
        "avg_precision": round(avg_precision, 3),
        "trend": trend,
    }

    # Add recency info from most recent observation
    latest = observations[-1]
    if latest.timestamp > 0:
        hours_ago = max(1, int((now - latest.timestamp) / 3600))
        result["last_observation"] = f"{hours_ago}h ago"

    # Count lessons applied (observations where something was learned)
    lessons = sum(1 for o in observations if o.touched_not_predicted)
    if lessons:
        result["lessons_applied"] = lessons

    return result


# ---------------------------------------------------------------------------
# Feature 4: Health Nudges
# ---------------------------------------------------------------------------


ACCURACY_DROP_THRESHOLD = 0.15
STALENESS_DAYS = 30
UNCOVERED_FILES_MIN = 3


def check_health_nudges(
    observations: List[ObservationLog],
    scope: str,
    repo_root: str = "",
    threshold_drop: float = ACCURACY_DROP_THRESHOLD,
) -> List[dict]:
    """Generate health warnings for a scope on resolve."""
    scope = normalize_relative_path(scope).rstrip("/")
    warnings = []

    # 1. Accuracy degradation
    if len(observations) >= 3:
        recalls = [o.recall for o in observations]
        mid = len(recalls) // 2
        if mid >= 1:
            older_avg = sum(recalls[:mid]) / mid
            recent_avg = sum(recalls[mid:]) / len(recalls[mid:])
            if older_avg - recent_avg >= threshold_drop:
                warnings.append({
                    "scope": scope,
                    "issue": "accuracy_degraded",
                    "message": (
                        f"{scope}/ accuracy has dropped"
                        f" from {older_avg:.0%} to {recent_avg:.0%}"
                    ),
                    "suggestion": f"dotscope health {scope}",
                })

    # 2. Staleness (scope refresh age + commits since)
    if repo_root:
        try:
            from .discovery import find_resolution_scope_with_source
            from .storage.incremental_state import (
                get_scope_refresh_epoch,
                load_incremental_state,
            )

            config, _source = find_resolution_scope_with_source(scope, root=repo_root)
            if config is not None:
                state = load_incremental_state(repo_root)
                refreshed_at = get_scope_refresh_epoch(repo_root, config.path, state=state)
                baseline = refreshed_at
                if baseline is None and os.path.exists(config.path):
                    baseline = os.path.getmtime(config.path)
                if baseline is not None:
                    days_since = int((time.time() - baseline) / 86400)
                    if days_since > STALENESS_DAYS:
                        commits = _count_commits_since(repo_root, config.includes, baseline)
                        if commits > 0:
                            warnings.append({
                                "scope": scope,
                                "issue": "stale",
                                "message": (
                                    f"{scope}/ hasn't been refreshed in {days_since} days"
                                    f" . {commits} commits have touched files in this scope"
                                ),
                                "suggestion": "dotscope refresh status",
                            })
        except Exception:
            pass

    # 3. Uncovered files
    if repo_root:
        uncovered = _count_uncovered_files(repo_root, scope)
        if uncovered > UNCOVERED_FILES_MIN:
            warnings.append({
                "scope": scope,
                "issue": "uncovered_files",
                "message": (
                    f"{scope}/ has {uncovered} files"
                    f" not covered by scope includes"
                ),
                "suggestion": f"dotscope ingest {scope}/",
            })

    return warnings


def _count_commits_since(repo_root: str, paths: List[str], since_ts: float) -> int:
    """Count commits touching any included path since a timestamp."""
    import subprocess
    from datetime import datetime, timezone

    normalized_paths = list(dict.fromkeys(
        normalize_relative_path(path) for path in paths if path
    ))
    if not normalized_paths:
        return 0

    since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline",
             f"--since={since_dt.isoformat()}",
             "--", *normalized_paths],
            capture_output=True, text=True, cwd=repo_root, timeout=10,
        )
        return len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
    except Exception:
        return 0


def _count_uncovered_files(repo_root: str, scope: str) -> int:
    """Count source files in a scope directory not covered by includes."""
    scope_dir = os.path.join(repo_root, scope)
    if not os.path.isdir(scope_dir):
        return 0

    source_exts = {".py", ".js", ".ts", ".go", ".rs", ".rb", ".java"}
    count = 0
    for dirpath, _dirs, filenames in os.walk(scope_dir):
        # Skip hidden dirs and common non-source dirs
        rel = os.path.relpath(dirpath, repo_root)
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv")
               for part in rel.split(os.sep)):
            continue
        for fn in filenames:
            if os.path.splitext(fn)[1] in source_exts:
                count += 1

    # Subtract the files that ARE in includes (rough: count files under scope/)
    # The includes typically have "scope/" which covers all, so uncovered = 0 in that case
    # Only flag if the scope file exists but doesn't include the directory
    try:
        from .discovery import find_resolution_scope

        config = find_resolution_scope(scope, root=repo_root)
        if config and any(
            inc.rstrip("/") == scope or inc.startswith(scope + "/")
            for inc in config.includes
        ):
            return 0
    except Exception:
        pass

    return count


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
