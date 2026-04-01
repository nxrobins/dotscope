"""Partition a codebase's search space into non-overlapping scout assignments."""

import os
from collections import defaultdict
from typing import Dict, List, Optional

from ..discovery import find_scope, load_index
from ..models.core import ScopesIndex


def partition_search_space(
    intent: str,
    n_partitions: int,
    repo_root: str,
    graph,
    index: Optional[ScopesIndex],
    invariants: dict,
) -> dict:
    """Divide an exploratory task into non-overlapping subgraphs.

    Uses semantic search to find relevant files, then scope boundaries
    and NPMI coupling to cleave them into decoupled partitions.
    """
    n_partitions = max(2, min(n_partitions, 10))

    # Step 1: Find relevant files via semantic search (or keyword fallback)
    relevant_files = _search_relevant_files(intent, repo_root, 50)

    if not relevant_files:
        return {
            "intent": intent,
            "partitions": [],
            "overlap_warnings": [],
            "uncovered_files": [],
        }

    # Step 2: Group by scope boundaries
    scope_groups = defaultdict(list)
    for filepath, score in relevant_files:
        scope_name = _find_covering_scope(filepath, index)
        scope_groups[scope_name or "__unscoped__"].append((filepath, score))

    # Step 3: Merge highly coupled groups using NPMI
    merged_groups = _merge_by_coupling(scope_groups, invariants)

    # Step 4: Rank groups by max relevance score and select top N
    ranked = sorted(
        merged_groups.items(),
        key=lambda g: max((s for _, s in g[1]), default=0),
        reverse=True,
    )

    partitions = []
    assigned_files = set()

    for i, (scope_name, file_scores) in enumerate(ranked[:n_partitions]):
        # Entry files: highest relevance in this group (max 3)
        file_scores.sort(key=lambda fs: -fs[1])
        entry_files = [f for f, _ in file_scores[:3]]

        # Context summary from scope
        scope = None
        if scope_name != "__unscoped__":
            scope = find_scope(scope_name, repo_root)
        summary = scope.description if scope else f"Files in {scope_name}"

        # Estimated trace depth from graph
        max_depth = max(
            (_estimate_trace_depth(f, graph) for f in entry_files),
            default=1,
        )

        # Max relevance score
        max_score = max((s for _, s in file_scores), default=0)

        partitions.append({
            "scout_id": i + 1,
            "primary_scope": scope_name,
            "entry_files": entry_files,
            "context_summary": summary,
            "estimated_depth": max_depth,
            "relevance_score": round(max_score, 2),
        })
        assigned_files.update(f for f, _ in file_scores)

    # Overlap detection
    overlap_warnings = _detect_partition_overlaps(partitions, graph)

    # Uncovered files
    uncovered = [f for f, _ in relevant_files if f not in assigned_files]

    return {
        "intent": intent,
        "partitions": partitions,
        "overlap_warnings": overlap_warnings,
        "uncovered_files": uncovered,
    }


def _search_relevant_files(
    intent: str, repo_root: str, top_k: int
) -> List[tuple]:
    """Search for files relevant to the intent. Returns [(filepath, score)]."""
    try:
        from ..search.retriever import search
        results = search(intent, repo_root, limit=top_k)
        # Deduplicate by file path, keep highest score
        seen = {}
        for r in results:
            if r.file_path not in seen or r.rrf_score > seen[r.file_path]:
                seen[r.file_path] = r.rrf_score
        return [(f, s) for f, s in seen.items()]
    except Exception:
        # Fallback: keyword match against file paths
        intent_words = intent.lower().split()
        matches = []
        if hasattr(graph, 'files'):
            for filepath in graph.files:
                path_lower = filepath.lower()
                score = sum(1 for w in intent_words if w in path_lower)
                if score > 0:
                    matches.append((filepath, score / len(intent_words)))
        return sorted(matches, key=lambda x: -x[1])[:top_k]


def _find_covering_scope(
    filepath: str, index: Optional[ScopesIndex]
) -> Optional[str]:
    """Find which scope covers a file path."""
    if not index:
        return None
    for name, entry in index.scopes.items():
        directory = getattr(entry, "directory", name)
        if filepath.startswith(directory + "/") or filepath.startswith(directory + os.sep):
            return name
    return None


def _merge_by_coupling(
    scope_groups: Dict[str, List[tuple]],
    invariants: dict,
) -> Dict[str, List[tuple]]:
    """Merge scope groups with high NPMI coupling between them."""
    contracts = invariants.get("contracts", [])
    merged = dict(scope_groups)

    for contract in contracts:
        if contract.get("confidence", 0) < 0.6:
            continue
        group_a = _find_group(contract.get("trigger_file", ""), merged)
        group_b = _find_group(contract.get("coupled_file", ""), merged)
        if group_a and group_b and group_a != group_b:
            if len(merged[group_a]) >= len(merged[group_b]):
                merged[group_a].extend(merged.pop(group_b))
            else:
                merged[group_b].extend(merged.pop(group_a))

    return merged


def _find_group(
    filepath: str, groups: Dict[str, List[tuple]]
) -> Optional[str]:
    """Find which group a file belongs to."""
    for name, files in groups.items():
        if any(f == filepath for f, _ in files):
            return name
    return None


def _estimate_trace_depth(entry_file: str, graph) -> int:
    """Estimate how deep a trace from this file goes via BFS."""
    visited = set()
    queue = [(entry_file, 0)]
    max_depth = 0

    while queue:
        current, depth = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        max_depth = max(max_depth, depth)

        if depth >= 10:
            continue

        node = graph.files.get(current) if hasattr(graph, 'files') else None
        if node:
            imports = getattr(node, 'imports', []) or []
            for imp in imports:
                if imp not in visited:
                    queue.append((imp, depth + 1))

    return min(max_depth, 10)


def _detect_partition_overlaps(
    partitions: List[dict], graph
) -> List[dict]:
    """Detect files that appear in multiple partitions' import neighborhoods."""
    warnings = []
    partition_files = {}

    for p in partitions:
        reachable = set()
        for entry in p["entry_files"]:
            _collect_reachable(entry, graph, reachable, max_depth=2)
        partition_files[p["scout_id"]] = reachable

    # Find overlaps
    seen = {}
    for scout_id, files in partition_files.items():
        for f in files:
            if f in seen:
                warnings.append({
                    "file": f,
                    "partitions": [seen[f], scout_id],
                })
            else:
                seen[f] = scout_id

    return warnings


def _collect_reachable(
    entry: str, graph, result: set, max_depth: int, depth: int = 0
):
    """Collect files reachable from entry within max_depth."""
    if entry in result or depth > max_depth:
        return
    result.add(entry)
    node = graph.files.get(entry) if hasattr(graph, 'files') else None
    if node:
        imports = getattr(node, 'imports', []) or []
        for imp in imports:
            _collect_reachable(imp, graph, result, max_depth, depth + 1)
