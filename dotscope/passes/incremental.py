"""Incremental scope update: evolve scopes on every commit.

Called by the post-commit hook. Updates scope includes (add/remove files),
file stabilities, and co-change tracking without a full re-ingest.
"""

import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from ..models.core import ScopeConfig
from ..parser import parse_scope_file, serialize_scope
from ..paths import normalize_directory_include, normalize_relative_path, scope_storage_key
from ..runtime_overlay import (
    ensure_runtime_scope_copy,
    load_effective_scope_configs,
    logical_scope_path,
    scope_name_from_logical_path,
)


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
        load_incremental_state,
        mark_scopes_refreshed,
        save_incremental_state,
    )

    changed_files = [normalize_relative_path(path) for path in changed_files]
    added_files = [normalize_relative_path(path) for path in added_files]
    deleted_files = [normalize_relative_path(path) for path in deleted_files]
    state = load_incremental_state(root)
    touched_scope_paths = set()

    # 1. Add new files to appropriate scope includes
    for filepath in added_files:
        scope_path = _find_covering_scope(root, filepath)
        if scope_path:
            touched_scope_paths.add(scope_path)
            _add_to_scope_includes(root, scope_path, filepath)
            scope_name = scope_name_from_logical_path(scope_path)
            print(
                f"dotscope: added {filepath} to {scope_name} scope",
                file=sys.stderr,
            )
        else:
            state.uncovered_new_files += 1

    # 2. Remove deleted files from scope includes
    for filepath in deleted_files:
        scope_path = _find_covering_scope(root, filepath)
        if scope_path:
            touched_scope_paths.add(scope_path)
            _remove_from_scope_includes(root, scope_path, filepath)

    # 3. Update file stabilities in invariants.json
    _update_stabilities(root, changed_files)

    # 4. Track state
    state.commits_since_last_full_ingest += 1
    state.last_incremental_commit = commit_hash
    impacted_scopes = set(_find_impacted_scope_paths(root, changed_files))
    impacted_scopes.update(touched_scope_paths)
    mark_scopes_refreshed(root, state, impacted_scopes)

    # 5. Prompt for full re-ingest if drifted too far
    if state.commits_since_last_full_ingest > 200:
        marker = os.path.join(root, ".dotscope", "needs_full_ingest")
        Path(marker).touch()

    save_incremental_state(root, state)


def _find_covering_scope(root: str, filepath: str) -> Optional[str]:
    """Find the .scope file whose directory covers this file path."""
    filepath = normalize_relative_path(filepath)
    parts = filepath.split("/")
    # Walk up from file to root looking for a .scope
    for i in range(len(parts) - 1, 0, -1):
        candidate_dir = "/".join(parts[:i])
        scope_path = logical_scope_path(f"{candidate_dir}/.scope")
        tracked = os.path.join(root, scope_path.replace("/", os.sep))
        runtime = ensure_runtime_scope_copy(root, scope_path)
        if runtime or os.path.exists(tracked):
            return scope_path
    return None


def _add_to_scope_includes(root: str, scope_path: str, filepath: str) -> None:
    """Add a file to a scope's includes list if not already present."""
    filepath = normalize_relative_path(filepath)
    runtime_path = ensure_runtime_scope_copy(root, scope_path)
    if runtime_path is None:
        return
    try:
        config = parse_scope_file(runtime_path)
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
    with open(runtime_path, "w", encoding="utf-8") as f:
        f.write(content)


def _remove_from_scope_includes(root: str, scope_path: str, filepath: str) -> None:
    """Remove a file from a scope's includes list."""
    filepath = normalize_relative_path(filepath)
    runtime_path = ensure_runtime_scope_copy(root, scope_path)
    if runtime_path is None:
        return
    try:
        config = parse_scope_file(runtime_path)
    except Exception:
        return

    if filepath in config.includes:
        config.includes.remove(filepath)
        content = serialize_scope(config)
        with open(runtime_path, "w", encoding="utf-8") as f:
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


def _find_impacted_scope_paths(root: str, filepaths: List[str]) -> List[str]:
    """Find every scope whose includes cover any changed file."""
    impacted = []
    changed = [normalize_relative_path(path) for path in filepaths if path]
    for scope_path, config, _source in load_effective_scope_configs(root):
        if any(_scope_covers_file(config, filepath, root) for filepath in changed):
            impacted.append(scope_path)

    return impacted


def _scope_covers_file(config: ScopeConfig, filepath: str, root: str) -> bool:
    """Return True when a scope include matches a changed file."""
    filepath = normalize_relative_path(filepath)
    scope_rel_path = scope_storage_key(config.path, root=root)
    if filepath == scope_rel_path:
        return True

    for include in config.includes:
        normalized = normalize_relative_path(include)
        if not normalized:
            continue

        if any(ch in normalized for ch in "*?[") and fnmatch.fnmatch(filepath, normalized):
            return True

        if filepath == normalized:
            return True

        include_prefix = normalized
        if not include_prefix.endswith("/"):
            include_abs = os.path.join(root, normalized.replace("/", os.sep))
            if os.path.isdir(include_abs):
                include_prefix = normalize_directory_include(normalized)

        if include_prefix.endswith("/") and filepath.startswith(include_prefix):
            return True

    return False
