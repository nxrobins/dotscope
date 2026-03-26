"""Persistent state for continuous ingest.

Tracks how many commits have passed since the last full ingest,
so dotscope can prompt for a full re-scan when incremental updates
have drifted far enough.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class IncrementalState:
    """State tracking for continuous ingest."""
    commits_since_last_full_ingest: int = 0
    last_full_ingest_timestamp: str = ""
    last_incremental_commit: str = ""
    uncovered_new_files: int = 0


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
            )
        except (json.JSONDecodeError, IOError):
            pass
    return IncrementalState()


def save_incremental_state(root: str, state: IncrementalState) -> None:
    """Persist incremental state to .dotscope/incremental.json."""
    dot_dir = os.path.join(root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)
    path = os.path.join(dot_dir, "incremental.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "commits_since_last_full_ingest": state.commits_since_last_full_ingest,
            "last_full_ingest_timestamp": state.last_full_ingest_timestamp,
            "last_incremental_commit": state.last_incremental_commit,
            "uncovered_new_files": state.uncovered_new_files,
        }, f, indent=2)


def reset_incremental_state(root: str) -> None:
    """Reset state after a full ingest."""
    import time
    state = IncrementalState(
        last_full_ingest_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    save_incremental_state(root, state)
