"""Persistent state for continuous ingest.

Tracks how many commits have passed since the last full ingest,
so dotscope can prompt for a full re-scan when incremental updates
have drifted far enough.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, Optional

from ..paths import scope_storage_key
from .atomic import atomic_write_json


@dataclass
class IncrementalState:
    """State tracking for continuous ingest."""
    commits_since_last_full_ingest: int = 0
    last_full_ingest_timestamp: str = ""
    last_incremental_commit: str = ""
    uncovered_new_files: int = 0
    scope_refresh_timestamps: Dict[str, str] = field(default_factory=dict)


def load_incremental_state(root: str) -> IncrementalState:
    """Load incremental state from .dotscope/incremental.json."""
    path = os.path.join(root, ".dotscope", "incremental.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return IncrementalState(
                commits_since_last_full_ingest=data.get("commits_since_last_full_ingest", 0),
                last_full_ingest_timestamp=data.get("last_full_ingest_timestamp", ""),
                last_incremental_commit=data.get("last_incremental_commit", ""),
                uncovered_new_files=data.get("uncovered_new_files", 0),
                scope_refresh_timestamps=data.get("scope_refresh_timestamps", {}),
            )
        except (json.JSONDecodeError, IOError):
            pass
    return IncrementalState()


def save_incremental_state(root: str, state: IncrementalState) -> None:
    """Persist incremental state to .dotscope/incremental.json."""
    dot_dir = os.path.join(root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)
    path = os.path.join(dot_dir, "incremental.json")
    atomic_write_json(path, {
        "commits_since_last_full_ingest": state.commits_since_last_full_ingest,
        "last_full_ingest_timestamp": state.last_full_ingest_timestamp,
        "last_incremental_commit": state.last_incremental_commit,
        "uncovered_new_files": state.uncovered_new_files,
        "scope_refresh_timestamps": state.scope_refresh_timestamps,
    })


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_refresh_timestamp(timestamp: str) -> Optional[float]:
    """Parse an ISO refresh timestamp to epoch seconds."""
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def mark_scope_refreshed(
    root: str,
    state: IncrementalState,
    scope_path: str,
    refreshed_at: Optional[str] = None,
) -> None:
    """Record the latest refresh timestamp for a scope file."""
    key = scope_storage_key(scope_path, root=root)
    if not key:
        return
    state.scope_refresh_timestamps[key] = refreshed_at or utc_now_iso()


def mark_scopes_refreshed(
    root: str,
    state: IncrementalState,
    scope_paths: Iterable[str],
    refreshed_at: Optional[str] = None,
) -> None:
    """Record refresh timestamps for multiple scope files."""
    stamp = refreshed_at or utc_now_iso()
    for scope_path in scope_paths:
        mark_scope_refreshed(root, state, scope_path, refreshed_at=stamp)


def get_scope_refresh_epoch(
    root: str,
    scope_path: str,
    state: Optional[IncrementalState] = None,
) -> Optional[float]:
    """Load the refresh timestamp for a scope file as epoch seconds."""
    current_state = state or load_incremental_state(root)
    key = scope_storage_key(scope_path, root=root)
    return parse_refresh_timestamp(current_state.scope_refresh_timestamps.get(key, ""))


def reset_incremental_state(
    root: str,
    scope_paths: Optional[Iterable[str]] = None,
) -> None:
    """Reset state after a full ingest."""
    refreshed_at = utc_now_iso()
    state = IncrementalState(
        last_full_ingest_timestamp=refreshed_at,
    )
    if scope_paths:
        mark_scopes_refreshed(root, state, scope_paths, refreshed_at=refreshed_at)
    save_incremental_state(root, state)
