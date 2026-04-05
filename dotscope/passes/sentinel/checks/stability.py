"""Stability concern check: large changes to stable files."""

from typing import Dict, List

from ..models import CheckCategory, CheckResult, Severity

# Threshold: a file is "stable" and a change is "large" above this
LARGE_CHANGE_LINES = 20


def check_stability(
    modified_files: List[str],
    diff_text: str,
    invariants: dict,
) -> List[CheckResult]:
    """Flag large changes to files classified as stable."""
    stabilities = invariants.get("file_stabilities", {})
    if not stabilities:
        return []

    # Count added lines per file in the diff
    file_additions = _count_additions(diff_text)
    results = []

    for filepath in modified_files:
        info = stabilities.get(filepath)
        if not info:
            continue

        classification = info.get("classification", "")
        if classification != "stable":
            continue

        additions = file_additions.get(filepath, 0)
        if additions < LARGE_CHANGE_LINES:
            continue

        commit_count = info.get("commit_count", 0)
        results.append(CheckResult(
            passed=False,
            category=CheckCategory.STABILITY,
            severity=Severity.NOTE,
            message=(
                f"{filepath}: stable file ({commit_count} commits), "
                f"this diff changes {additions} lines"
            ),
            detail="Large changes to stable files deserve extra review",
            file=filepath,
            source_file="invariants.json",
            source_rule=f"stability:{filepath}",
        ))

    return results


def _count_additions(diff_text: str) -> Dict[str, int]:
    """Count added lines per file in a unified diff."""
    counts: Dict[str, int] = {}
    current_file = ""

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else ""
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            counts[current_file] = counts.get(current_file, 0) + 1

    return counts
