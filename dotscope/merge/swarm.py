"""Swarm Lock: semantic mutex for multi-agent codebases.

Transforms the MCP server into an Air Traffic Controller using a
persistent state ledger and the DependencyGraph. Each agent claims
a scope, and dotscope computes a dampened blast radius to prevent
file collisions.

Blast radius dampening:
  Depth 1 (direct dependents) → exclusive_files: hard block
  Depth 2 (two-hop dependents) → shared_files: soft warning
  Depth 3+ → no lock (handled by AST Merge Driver if conflicts arise)
"""

import time
from typing import Dict, List, Optional, Set, Tuple

from ..storage.swarm_state import (
    ConflictDescriptor,
    SwarmLock,
    SwarmState,
    DEFAULT_LOCK_TTL,
    _acquire_swarm_lock,
    _generate_lock_id,
    _release_swarm_lock,
    find_overlaps,
    gc_expired_locks,
    load_swarm_state,
    save_swarm_state,
)


# ---------------------------------------------------------------------------
# Blast radius computation
# ---------------------------------------------------------------------------

def compute_blast_radius(
    primary_files: List[str],
    graph_hubs: Dict[str, dict],
    network_edges: Optional[Dict[str, Dict[str, list]]] = None,
    reverse_network_edges: Optional[Dict[str, List[str]]] = None,
    co_change_index: Optional[Dict[str, Dict[str, float]]] = None,
) -> Tuple[List[str], List[str]]:
    """Compute the dampened blast radius for a set of primary files.

    Args:
        primary_files: Files the agent explicitly wants to modify.
        graph_hubs: {path: {"imported_by_count", "imported_by_dirs"}} from cache.
        network_edges: Provider→consumer network edges.
        reverse_network_edges: Consumer→provider reverse edges.
        co_change_index: NPMI co-change pairs.

    Returns:
        (exclusive_files, shared_files) — depth-1 and depth-2 dependents.
    """
    primary_set = set(primary_files)
    exclusive: Set[str] = set()
    shared: Set[str] = set()

    for f in primary_files:
        # Depth 1: direct dependents → exclusive
        hub = graph_hubs.get(f, {})
        imported_by = hub.get("imported_by_files", [])
        if isinstance(imported_by, list):
            for dep in imported_by:
                if dep not in primary_set:
                    exclusive.add(dep)

        # Depth 1: network consumers (cross-language) → exclusive
        if network_edges and f in network_edges:
            for consumer in network_edges[f]:
                if consumer not in primary_set:
                    exclusive.add(consumer)

        # Depth 1: network providers (reverse direction) → exclusive
        if reverse_network_edges and f in reverse_network_edges:
            for provider in reverse_network_edges[f]:
                if provider not in primary_set:
                    exclusive.add(provider)

        # Depth 1: high-NPMI co-change partners → exclusive
        if co_change_index and f in co_change_index:
            for partner, npmi in co_change_index[f].items():
                if npmi > 0.5 and partner not in primary_set:
                    exclusive.add(partner)

    # Depth 2: dependents of exclusive files → shared
    for f in list(exclusive):
        hub = graph_hubs.get(f, {})
        imported_by = hub.get("imported_by_files", [])
        if isinstance(imported_by, list):
            for dep in imported_by:
                if dep not in primary_set and dep not in exclusive:
                    shared.add(dep)

    return sorted(exclusive), sorted(shared)


# ---------------------------------------------------------------------------
# Claim / Release / Renew
# ---------------------------------------------------------------------------

def claim_scope(
    repo_root: str,
    agent_id: str,
    task_description: str,
    primary_files: List[str],
    graph_hubs: Dict[str, dict],
    network_edges: Optional[dict] = None,
    reverse_network_edges: Optional[dict] = None,
    co_change_index: Optional[dict] = None,
    ttl: float = DEFAULT_LOCK_TTL,
) -> dict:
    """Attempt to claim a scope for an agent.

    Returns:
        {"status": "granted"|"rejected"|"warning",
         "lock_id": str,
         "exclusive_files": [...],
         "shared_files": [...],
         "conflicts": [...]}
    """
    exclusive, shared = compute_blast_radius(
        primary_files, graph_hubs, network_edges,
        reverse_network_edges, co_change_index,
    )

    fd = _acquire_swarm_lock(repo_root)
    try:
        state = load_swarm_state(repo_root)
        gc_expired_locks(state)

        overlaps = find_overlaps(state, exclusive, shared, agent_id)

        if overlaps["exclusive"]:
            # Hard block — another agent holds exclusive lock on these files
            conflict_locks = [state.locks[lid] for lid in overlaps["exclusive"]]
            conflict_files = set()
            for lock in conflict_locks:
                conflict_files.update(set(exclusive) & set(lock.exclusive_files))

            conflict_id = f"conflict_{agent_id}_{int(time.time())}"
            state.conflicts[conflict_id] = ConflictDescriptor(
                conflict_id=conflict_id,
                files=sorted(conflict_files),
                agents=[agent_id] + [l.agent_id for l in conflict_locks],
                conflict_type="exclusive_overlap",
                created_at=time.time(),
                detail=f"Agent {agent_id} tried to claim files locked by "
                       f"{', '.join(l.agent_id for l in conflict_locks)}",
            )
            save_swarm_state(repo_root, state)

            return {
                "status": "rejected",
                "lock_id": "",
                "exclusive_files": exclusive,
                "shared_files": shared,
                "conflicts": [
                    {
                        "lock_id": lid,
                        "agent": state.locks[lid].agent_id,
                        "files": sorted(set(exclusive) & set(state.locks[lid].exclusive_files)),
                    }
                    for lid in overlaps["exclusive"]
                ],
            }

        # Grant the lock (with shared warnings if applicable)
        now = time.time()
        lock_id = _generate_lock_id(agent_id)
        lock = SwarmLock(
            agent_id=agent_id,
            task_description=task_description,
            primary_files=primary_files,
            exclusive_files=exclusive,
            shared_files=shared,
            created_at=now,
            expires_at=now + ttl,
            lock_id=lock_id,
        )
        state.locks[lock_id] = lock
        save_swarm_state(repo_root, state)
    finally:
        _release_swarm_lock(repo_root, fd)

    status = "warning" if overlaps["shared"] else "granted"
    result = {
        "status": status,
        "lock_id": lock_id,
        "exclusive_files": exclusive,
        "shared_files": shared,
        "conflicts": [],
    }

    if overlaps["shared"]:
        result["warnings"] = [
            {
                "lock_id": lid,
                "agent": state.locks[lid].agent_id,
                "shared_overlap": sorted(set(shared) & set(state.locks[lid].exclusive_files)),
            }
            for lid in overlaps["shared"]
        ]

    # Pre-flight advisory
    try:
        from ..passes.preflight import compute_preflight
        result["preflight"] = compute_preflight(
            claimed_files=primary_files,
            repo_root=repo_root,
        )
    except Exception:
        result["preflight"] = {"risk_level": "unknown"}

    return result


def release_lock(repo_root: str, lock_id: str) -> bool:
    """Release a lock. Returns True if found and removed."""
    fd = _acquire_swarm_lock(repo_root)
    try:
        state = load_swarm_state(repo_root)
        if lock_id in state.locks:
            del state.locks[lock_id]
            save_swarm_state(repo_root, state)
            return True
        return False
    finally:
        _release_swarm_lock(repo_root, fd)


def renew_lock(repo_root: str, lock_id: str, ttl: float = DEFAULT_LOCK_TTL) -> bool:
    """Extend a lock's expiry. Returns True if found and renewed."""
    state = load_swarm_state(repo_root)
    if lock_id in state.locks:
        state.locks[lock_id].expires_at = time.time() + ttl
        save_swarm_state(repo_root, state)
        return True
    return False


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

ESCALATION_THRESHOLD = 2


def check_escalation(repo_root: str, conflict_id: str) -> Optional[dict]:
    """Increment resolution_attempts. If >= threshold, return escalation payload."""
    state = load_swarm_state(repo_root)
    conflict = state.conflicts.get(conflict_id)
    if not conflict:
        return None

    conflict.resolution_attempts += 1
    save_swarm_state(repo_root, state)

    if conflict.resolution_attempts >= ESCALATION_THRESHOLD:
        # Build escalation payload with full context
        active_locks = {
            lid: {
                "agent": lock.agent_id,
                "task": lock.task_description,
                "exclusive": lock.exclusive_files,
                "shared": lock.shared_files,
                "expires": lock.expires_at,
            }
            for lid, lock in state.locks.items()
        }

        return {
            "escalation": True,
            "conflict": {
                "id": conflict.conflict_id,
                "type": conflict.conflict_type,
                "files": conflict.files,
                "agents": conflict.agents,
                "attempts": conflict.resolution_attempts,
            },
            "active_locks": active_locks,
            "message": (
                f"Conflict {conflict.conflict_id} has failed {conflict.resolution_attempts} "
                f"resolution attempts. Escalating to human operator."
            ),
        }

    return None  # Not yet at threshold


# ---------------------------------------------------------------------------
# Sentinel integration
# ---------------------------------------------------------------------------

def is_any_lock_active(repo_root: str, file_path: str) -> bool:
    """Check if any active lock covers a specific file path."""
    state = load_swarm_state(repo_root)
    gc_expired_locks(state)

    for lock in state.locks.values():
        all_files = set(lock.primary_files + lock.exclusive_files + lock.shared_files)
        if file_path in all_files:
            return True
    return False


def check_swarm_locks(
    modified_files: List[str],
    agent_id: Optional[str],
    repo_root: str,
) -> list:
    """Check if modified files violate active swarm locks.

    Returns a list of CheckResult-compatible dicts.
    """
    state = load_swarm_state(repo_root)
    gc_expired_locks(state)

    if not state.locks:
        return []

    modified_set = set(modified_files)
    results = []

    for lock_id, lock in state.locks.items():
        if lock.agent_id == agent_id:
            continue  # Don't block the lock holder

        # Check exclusive violations
        violated = modified_set & set(lock.exclusive_files)
        if violated:
            results.append({
                "passed": False,
                "category": "swarm_lock",
                "severity": "hold",
                "message": f"Swarm Lock violation: {sorted(violated)} exclusively locked by {lock.agent_id}",
                "detail": (
                    f"Agent {lock.agent_id} holds an exclusive lock on these files "
                    f"(task: {lock.task_description}). "
                    f"Lock expires at {time.strftime('%H:%M:%S', time.localtime(lock.expires_at))}."
                ),
                "lock_id": lock_id,
                "lock_agent": lock.agent_id,
            })

    return results
