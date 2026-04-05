"""Spatial co-location check: files should live near their dependents.

Orphan Rule: A file imported by only one other file should live in the
same directory as its parent.

Shared Rule: A file imported by files across multiple directories should
live at their Lowest Common Ancestor, or shared/utils/ if LCA is root.

These are NOTEs (informational), never blocking.
"""

import os
from typing import Dict, List, Optional

from ..models import CheckCategory, CheckResult, Severity


def check_colocation(
    modified_files: List[str],
    graph_hubs: Dict[str, dict],
    repo_root: str,
) -> List[CheckResult]:
    """Check if modified files are co-located with their dependents.

    Args:
        modified_files: Relative paths of files changed in the diff.
        graph_hubs: {path: {"imported_by_count": int, "imported_by_dirs": [str]}}.
        repo_root: Repository root for path resolution.
    """
    results = []

    for filepath in modified_files:
        hub = graph_hubs.get(filepath)
        if not hub:
            continue

        count = hub.get("imported_by_count", 0)
        dirs = hub.get("imported_by_dirs", [])

        if count == 0:
            continue  # Standalone script, no rule applies

        file_dir = os.path.dirname(filepath)
        suggested = determine_colocation_target(filepath, count, dirs)

        if suggested is None:
            continue

        suggested_dir = os.path.dirname(suggested)
        if _dirs_equivalent(file_dir, suggested_dir):
            continue  # Already co-located correctly

        if count == 1:
            rule = "Orphan Rule"
            detail = (
                f"This file is only imported by one module (in {dirs[0]}). "
                f"Consider moving it to {suggested_dir}/ to keep related code together."
            )
        else:
            rule = "Shared Rule"
            detail = (
                f"This file is imported by {count} modules across {len(set(dirs))} directories. "
                f"The Lowest Common Ancestor is {suggested_dir}/."
            )

        results.append(CheckResult(
            passed=False,
            category=CheckCategory.BOUNDARY,
            severity=Severity.NOTE,
            message=f"Spatial {rule}: {filepath} could live in {suggested_dir}/",
            detail=detail,
            file=filepath,
            suggestion=f"Consider: git mv {filepath} {suggested}",
            can_acknowledge=True,
            acknowledge_id=f"spatial_{filepath.replace('/', '_').replace('.', '_')}",
            source_file="heuristic",
            source_rule=f"spatial_colocation:{rule.lower().replace(' ', '_')}",
        ))

    return results


def determine_colocation_target(
    filepath: str,
    imported_by_count: int,
    imported_by_dirs: List[str],
) -> Optional[str]:
    """Determine where a file should live based on its import edges.

    Returns the suggested path, or None if no suggestion.
    """
    if imported_by_count == 0 or not imported_by_dirs:
        return None

    filename = os.path.basename(filepath)

    if imported_by_count == 1:
        # Orphan Rule: move to parent's directory
        parent_dir = imported_by_dirs[0]
        return os.path.join(parent_dir, filename)

    # Shared Rule: find Lowest Common Ancestor
    unique_dirs = list(set(imported_by_dirs))
    lca_dir = os.path.commonpath(unique_dirs) if unique_dirs else ""

    # If LCA is root, push to shared/utils to prevent root clutter
    if lca_dir == "" or lca_dir == ".":
        return os.path.join("shared", "utils", filename)

    return os.path.join(lca_dir, filename)


def _dirs_equivalent(dir_a: str, dir_b: str) -> bool:
    """Check if two directory paths are equivalent."""
    a = os.path.normpath(dir_a) if dir_a else ""
    b = os.path.normpath(dir_b) if dir_b else ""
    return a == b
