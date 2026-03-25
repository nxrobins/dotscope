"""Near-miss detection: disasters that didn't happen.

Extracts warning pairs from scope context, compares against commit diffs,
and stores detected near-misses for the agent channel.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class WarningPair:
    """An extracted (anti_pattern, safe_pattern) pair from scope context."""
    anti_pattern: str
    safe_pattern: str
    context_line: str
    scope: str


@dataclass
class NearMiss:
    """A detected near-miss event."""
    scope: str
    event: str
    context_used: str
    potential_impact: str


# Regex patterns for extracting warning pairs from context
_PAIR_PATTERNS = [
    # "Never call .delete(), use .deactivate()"
    r"[Nn]ever\s+(?:call\s+)?(\S+).*?use\s+(\S+)",
    # "Don't use X, use Y instead"
    r"[Dd]on'?t\s+(?:use\s+)?(\S+).*?use\s+(\S+)",
    # "Avoid X — use Y"
    r"[Aa]void\s+(\S+).*?use\s+(\S+)",
    # "X is deprecated, use Y"
    r"(\S+)\s+is\s+deprecated.*?use\s+(\S+)",
]


def extract_warning_pairs(
    scope_name: str, context: str,
) -> List[WarningPair]:
    """Extract (anti_pattern, safe_pattern) pairs from scope context."""
    pairs = []
    for line in context.splitlines():
        stripped = line.strip().lstrip("- ")
        if not stripped:
            continue
        for pattern in _PAIR_PATTERNS:
            match = re.search(pattern, stripped)
            if match:
                pairs.append(WarningPair(
                    anti_pattern=match.group(1).strip(".,;:()"),
                    safe_pattern=match.group(2).strip(".,;:()"),
                    context_line=stripped,
                    scope=scope_name,
                ))
                break
    return pairs


def detect_near_misses(
    diff_text: str,
    scope_contexts: Dict[str, str],
) -> List[NearMiss]:
    """Detect near-misses by comparing commit diff against scope warnings.

    Args:
        diff_text: The full commit diff
        scope_contexts: {scope_name: context_str} for scopes resolved in session
    """
    if not diff_text:
        return []

    near_misses = []
    diff_lower = diff_text.lower()

    for scope_name, context in scope_contexts.items():
        if not context:
            continue

        pairs = extract_warning_pairs(scope_name, context)
        for pair in pairs:
            anti_in_diff = pair.anti_pattern.lower() in diff_lower
            safe_in_diff = pair.safe_pattern.lower() in diff_lower

            if safe_in_diff and not anti_in_diff:
                near_misses.append(NearMiss(
                    scope=scope_name,
                    event=(
                        f"Agent used {pair.safe_pattern}"
                        f" instead of {pair.anti_pattern}"
                    ),
                    context_used=pair.context_line,
                    potential_impact=(
                        f"Using {pair.anti_pattern} instead of {pair.safe_pattern}"
                        f" would have violated the constraint:"
                        f" {pair.context_line}"
                    ),
                ))

    return near_misses[:5]  # Cap


def store_near_misses(root: str, near_misses: List[NearMiss]) -> None:
    """Append near-misses to .dotscope/near_misses.jsonl."""
    path = Path(root) / ".dotscope" / "near_misses.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        for nm in near_misses:
            f.write(json.dumps({
                "scope": nm.scope,
                "event": nm.event,
                "context_used": nm.context_used,
                "potential_impact": nm.potential_impact,
                "timestamp": time.time(),
            }) + "\n")

    # Cap at 100 entries
    _truncate_jsonl(path, max_entries=100)


def load_recent_near_misses(
    root: str, scope: str, max_age_hours: int = 48,
) -> List[dict]:
    """Load near-misses from .dotscope/near_misses.jsonl."""
    path = Path(root) / ".dotscope" / "near_misses.jsonl"
    if not path.exists():
        return []

    cutoff = time.time() - (max_age_hours * 3600)
    results = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("scope") != scope:
                continue
            if entry.get("timestamp", 0) < cutoff:
                continue
            hours_ago = max(1, int((time.time() - entry["timestamp"]) / 3600))
            results.append({
                "event": entry["event"],
                "context_used": entry["context_used"],
                "potential_impact": entry["potential_impact"],
                "detected": f"{hours_ago}h ago",
            })
    except (json.JSONDecodeError, KeyError):
        pass

    return results


def save_session_scopes(root: str, scopes: list) -> None:
    """Write resolved scopes to .dotscope/last_session.json for post-commit hook."""
    if not scopes:
        return
    path = Path(root) / ".dotscope" / "last_session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "scopes": scopes,
        "ended_at": time.time(),
    }), encoding="utf-8")


def load_session_scopes(root: str) -> List[str]:
    """Load scopes from the last MCP session."""
    path = Path(root) / ".dotscope" / "last_session.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Only use if session ended within 4 hours
        if time.time() - data.get("ended_at", 0) > 14400:
            return []
        return data.get("scopes", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _truncate_jsonl(path: Path, max_entries: int = 100) -> None:
    """Keep only the last N entries in a JSONL file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_entries:
            path.write_text(
                "\n".join(lines[-max_entries:]) + "\n",
                encoding="utf-8",
            )
    except Exception:
        pass
