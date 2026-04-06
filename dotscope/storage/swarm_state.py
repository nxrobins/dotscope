"""Swarm Lock state persistence.

Manages .dotscope/cache/swarm_state.json — the ledger of active agent
locks, their blast radii, and conflict descriptors.
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SwarmLock:
    """A single agent's claim on a set of files."""
    agent_id: str
    task_description: str
    primary_files: List[str]       # Files the agent explicitly requested
    exclusive_files: List[str]     # Depth 1: hard block for other agents
    shared_files: List[str]        # Depth 2: soft warning for other agents
    created_at: float = 0.0
    expires_at: float = 0.0
    lock_id: str = ""


@dataclass
class ConflictDescriptor:
    """A detected conflict between agents."""
    conflict_id: str
    files: List[str]
    agents: List[str]
    conflict_type: str             # "exclusive_overlap", "shared_overlap", "merge_conflict"
    resolution_attempts: int = 0
    created_at: float = 0.0
    detail: str = ""


@dataclass
class SwarmState:
    """Full swarm state ledger."""
    locks: Dict[str, SwarmLock] = field(default_factory=dict)      # lock_id → SwarmLock
    conflicts: Dict[str, ConflictDescriptor] = field(default_factory=dict)  # conflict_id → desc
    version: int = 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _state_path(repo_root: str) -> Path:
    return Path(repo_root) / ".dotscope" / "cache" / "swarm_state.json"


def _lock_path(repo_root: str) -> str:
    return os.path.join(repo_root, ".dotscope", "cache", "swarm_state.json.lock")


def _acquire_swarm_lock(root: str, timeout: float = 5.0) -> int:
    """Acquire a cross-platform file lock for swarm state access.

    Returns the file descriptor on success.
    Raises ``TimeoutError`` if the lock cannot be acquired within *timeout* seconds.
    """
    lock = _lock_path(root)
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR)

    deadline = time.monotonic() + timeout
    while True:
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except (OSError, IOError):
            if time.monotonic() >= deadline:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise TimeoutError(
                    f"Could not acquire swarm state lock at {lock} "
                    f"within {timeout}s"
                )
            time.sleep(0.05)


def _release_swarm_lock(root: str, fd: int) -> None:
    """Release the cross-platform file lock."""
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except (OSError, IOError):
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def load_swarm_state(repo_root: str) -> SwarmState:
    """Load swarm state from disk, or return empty state."""
    path = _state_path(repo_root)
    if not path.exists():
        return SwarmState()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = SwarmState()

        for lock_id, lock_data in data.get("locks", {}).items():
            state.locks[lock_id] = SwarmLock(**lock_data)

        for conf_id, conf_data in data.get("conflicts", {}).items():
            state.conflicts[conf_id] = ConflictDescriptor(**conf_data)

        return state
    except (json.JSONDecodeError, TypeError, KeyError):
        return SwarmState()


def save_swarm_state(repo_root: str, state: SwarmState) -> None:
    """Persist swarm state to disk."""
    path = _state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "version": state.version,
        "locks": {lid: asdict(lock) for lid, lock in state.locks.items()},
        "conflicts": {cid: asdict(c) for cid, c in state.conflicts.items()},
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

DEFAULT_LOCK_TTL = 30 * 60  # 30 minutes


def _generate_lock_id(agent_id: str) -> str:
    """Generate a unique lock ID."""
    import hashlib
    return hashlib.md5(f"{agent_id}:{time.time()}".encode()).hexdigest()[:12]


def gc_expired_locks(state: SwarmState) -> int:
    """Remove expired locks and orphaned conflicts. Returns count of removed locks."""
    now = time.time()
    expired = [lid for lid, lock in state.locks.items() if lock.expires_at < now]
    for lid in expired:
        del state.locks[lid]

    # Clean up orphaned ConflictDescriptors whose referenced agents
    # no longer hold any active lock.
    active_agents = {lock.agent_id for lock in state.locks.values()}
    orphaned = [
        cid for cid, conflict in state.conflicts.items()
        if not any(agent in active_agents for agent in conflict.agents)
    ]
    for cid in orphaned:
        del state.conflicts[cid]

    return len(expired)


def find_overlaps(
    state: SwarmState,
    exclusive_files: List[str],
    shared_files: List[str],
    requesting_agent: str,
) -> Dict[str, List[str]]:
    """Check if requested files overlap with existing locks.

    Returns:
        {"exclusive": [conflicting_lock_ids], "shared": [warning_lock_ids]}
    """
    gc_expired_locks(state)
    exclusive_set = set(exclusive_files)
    shared_set = set(shared_files)

    conflicts = {"exclusive": [], "shared": []}

    for lock_id, lock in state.locks.items():
        if lock.agent_id == requesting_agent:
            continue  # Don't conflict with self

        # Check exclusive-exclusive overlap (hard block)
        if exclusive_set & set(lock.exclusive_files):
            conflicts["exclusive"].append(lock_id)

        # Check exclusive-shared overlap (warning)
        elif shared_set & set(lock.exclusive_files):
            conflicts["shared"].append(lock_id)

        # Check shared-exclusive overlap (warning)
        elif exclusive_set & set(lock.shared_files):
            conflicts["shared"].append(lock_id)

    return conflicts
