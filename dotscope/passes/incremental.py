"""Incremental scope update: evolve scopes on every commit.

Called by the post-commit hook. Updates scope includes (add/remove files),
file stabilities, and co-change tracking without a full re-ingest.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..models.core import ScopeConfig
from ..parser import parse_scope_file, serialize_scope


def incremental_update(
    root: str,
    changed_files: List[str],
    added_files: List[str],
    deleted_files: List[str],
    commit_hash: str,
) -> None:
    """Update scopes incrementally after a commit.

    Fast path: no AST analysis, no graph building. Just file-list
    diffing and JSON counter updates.
    """
    from ..storage.incremental_state import (
        load_incremental_state, save_incremental_state,
    )

    state = load_incremental_state(root)

    # 1. Add new files to appropriate scope includes
    for filepath in added_files:
        scope_path = _find_covering_scope(root, filepath)
        if scope_path:
            _add_to_scope_includes(scope_path, filepath)
            print(
                f"dotscope: added {filepath} to {os.path.dirname(os.path.relpath(scope_path, root))} scope",
                file=sys.stderr,
            )
        else:
            state.uncovered_new_files += 1

    # 2. Remove deleted files from scope includes
    for filepath in deleted_files:
        scope_path = _find_covering_scope(root, filepath)
        if scope_path:
            _remove_from_scope_includes(scope_path, filepath)

    # 3. Update file stabilities in invariants.json
    _update_stabilities(root, changed_files)

    # 4. Track state
    state.commits_since_last_full_ingest += 1
    state.last_incremental_commit = commit_hash

    # 5. Prompt for full re-ingest if drifted too far
    if state.commits_since_last_full_ingest > 200:
        marker = os.path.join(root, ".dotscope", "needs_full_ingest")
        Path(marker).touch()

    save_incremental_state(root, state)


def _find_covering_scope(root: str, filepath: str) -> Optional[str]:
    """Find the .scope file whose directory covers this file path."""
    parts = filepath.split("/")
    # Walk up from file to root looking for a .scope
    for i in range(len(parts) - 1, 0, -1):
        candidate_dir = "/".join(parts[:i])
        scope_path = os.path.join(root, candidate_dir, ".scope")
        if os.path.exists(scope_path):
            return scope_path
    return None


def _add_to_scope_includes(scope_path: str, filepath: str) -> None:
    """Add a file to a scope's includes list if not already present."""
    try:
        config = parse_scope_file(scope_path)
    except Exception:
        return

    # Check if already covered by a directory include
    for inc in config.includes:
        if inc.endswith("/") and filepath.startswith(inc):
            return
        if filepath == inc:
            return

    config.includes.append(filepath)
    content = serialize_scope(config)
    with open(scope_path, "w", encoding="utf-8") as f:
        f.write(content)


def _remove_from_scope_includes(scope_path: str, filepath: str) -> None:
    """Remove a file from a scope's includes list."""
    try:
        config = parse_scope_file(scope_path)
    except Exception:
        return

    if filepath in config.includes:
        config.includes.remove(filepath)
        content = serialize_scope(config)
        with open(scope_path, "w", encoding="utf-8") as f:
            f.write(content)


def _update_stabilities(root: str, changed_files: List[str]) -> None:
    """Increment commit counts and reclassify stability for changed files."""
    inv_path = os.path.join(root, ".dotscope", "invariants.json")
    if not os.path.exists(inv_path):
        return

    try:
        with open(inv_path, "r", encoding="utf-8") as f:
            invariants = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    stabilities = invariants.get("file_stabilities", {})
    updated = False

    for filepath in changed_files:
        if filepath in stabilities:
            stabilities[filepath]["commit_count"] = stabilities[filepath].get("commit_count", 0) + 1
            count = stabilities[filepath]["commit_count"]
            # Reclassify
            if count >= 20:
                stabilities[filepath]["classification"] = "volatile"
            elif count >= 5:
                stabilities[filepath]["classification"] = "tweaked"
            updated = True
        else:
            stabilities[filepath] = {
                "classification": "stable",
                "commit_count": 1,
            }
            updated = True

    if updated:
        invariants["file_stabilities"] = stabilities
        with open(inv_path, "w", encoding="utf-8") as f:
            json.dump(invariants, f, indent=2)
