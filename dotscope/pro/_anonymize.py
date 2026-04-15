"""Topology anonymization for Pro API payloads.

The Pro backend must never see source code, file paths, module names, or any
identifier that could de-anonymize a user's repo. This module converts a
``DependencyGraph`` into a pure topology dict containing only integers:
node count, edges by id, degree distributions, and a LOC vector (already a
numeric shape feature).

Node IDs are assigned from a cryptographically-random permutation so the same
path maps to a different ID on every call, preventing cross-request
fingerprinting at the server side.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, List


def _shuffled_indices(n: int) -> List[int]:
    """Return a cryptographically-random permutation of ``range(n)``.

    Uses :func:`secrets.randbelow` so the assignment differs across calls and
    cannot be predicted by the server.
    """
    indices = list(range(n))
    # Fisher-Yates with CSPRNG
    for i in range(n - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        indices[i], indices[j] = indices[j], indices[i]
    return indices


def anonymize_graph(graph: Any) -> Dict[str, Any]:
    """Emit a topology-only dict from a ``DependencyGraph``.

    The output contains *no* strings sourced from the original repo. Only
    node counts, integer edge pairs, degree distributions, and per-node LOC.
    """
    # Accept a dataclass DependencyGraph or any object exposing ``files`` dict.
    files = getattr(graph, "files", None) or {}
    paths = list(files.keys())
    n = len(paths)

    if n == 0:
        return {
            "node_count": 0,
            "edges": [],
            "in_degrees": [],
            "out_degrees": [],
            "loc_per_node": [],
        }

    # Shuffled ID assignment: path -> int
    shuffled = _shuffled_indices(n)
    path_to_id = {path: shuffled[i] for i, path in enumerate(paths)}

    edges: List[List[int]] = []
    in_degrees = [0] * n
    out_degrees = [0] * n
    loc_per_node = [0] * n

    for path, node in files.items():
        src_id = path_to_id[path]
        # LOC is a numeric feature; fall back to 0 if the node doesn't track it.
        loc_per_node[src_id] = int(getattr(node, "loc", 0) or 0)

        for imp in getattr(node, "imports", []) or []:
            dst_id = path_to_id.get(imp)
            if dst_id is None:
                # External dependency (not a tracked file) — skip; we only
                # send in-repo topology, never external identifiers.
                continue
            edges.append([src_id, dst_id])
            out_degrees[src_id] += 1
            in_degrees[dst_id] += 1

    return {
        "node_count": n,
        "edges": edges,
        "in_degrees": in_degrees,
        "out_degrees": out_degrees,
        "loc_per_node": loc_per_node,
    }
