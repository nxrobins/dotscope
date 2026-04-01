"""Resolve context along a specific execution path through the dependency graph."""

import os
from typing import Dict, List, Optional, Tuple

from ..discovery import find_scope
from ..models.core import ScopesIndex
from ..tokens import estimate_tokens


def resolve_trace(
    entry_file: str,
    max_depth: int,
    focus: Optional[str],
    repo_root: str,
    graph,
    index: Optional[ScopesIndex],
    invariants: dict,
) -> dict:
    """Follow imports from entry_file, collecting context along the path.

    BFS through the dependency graph, prioritizing imports in the same scope
    or with high NPMI to the entry file. Hard cap of 50 files to prevent
    exponential fan-out.
    """
    max_depth = min(max(max_depth, 1), 10)
    max_files = 50

    # BFS with priority scoring
    trace_path = []
    visited = set()
    queue = [(entry_file, 0)]
    entry_scope = _find_covering_scope(entry_file, index)

    while queue and len(visited) < max_files:
        current, depth = queue.pop(0)
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        trace_path.append(current)

        node = graph.files.get(current) if hasattr(graph, 'files') else None
        if not node:
            continue

        imports = getattr(node, 'imports', []) or []
        candidates = []
        for imp in imports:
            if imp in visited:
                continue

            imp_scope = _find_covering_scope(imp, index)
            npmi = _get_npmi(current, imp, invariants)

            # Keep internal files, drop external with no scope and low NPMI
            is_internal = imp in (graph.files if hasattr(graph, 'files') else {})
            if not is_internal and not imp_scope and npmi < 0.3:
                continue

            score = 0.0
            if imp_scope == entry_scope and entry_scope is not None:
                score += 2.0
            score += npmi
            if is_internal and not imp_scope:
                score += 0.1
            candidates.append((imp, depth + 1, score))

        # Follow highest-scored imports first
        candidates.sort(key=lambda c: -c[2])
        for imp, d, _ in candidates:
            queue.append((imp, d))

    # Track max depth reached
    depth_reached = 0
    depth_visited = set()
    depth_queue = [(entry_file, 0)]
    while depth_queue:
        current, d = depth_queue.pop(0)
        if current in depth_visited or d > max_depth:
            continue
        depth_visited.add(current)
        depth_reached = max(depth_reached, d)
        if current in trace_path:
            node = graph.files.get(current) if hasattr(graph, 'files') else None
            if node:
                for imp in (getattr(node, 'imports', []) or []):
                    if imp in visited and imp not in depth_visited:
                        depth_queue.append((imp, d + 1))

    # Identify scopes crossed
    scopes_crossed = []
    seen_scopes = set()
    for filepath in trace_path:
        scope_name = _find_covering_scope(filepath, index)
        if scope_name and scope_name not in seen_scopes:
            scopes_crossed.append(scope_name)
            seen_scopes.add(scope_name)

    # Build unified context: only sections relevant to trace files
    context_parts = []
    for scope_name in scopes_crossed:
        scope = find_scope(scope_name, repo_root)
        if not scope:
            continue

        context_str = getattr(scope, 'context_str', '') or str(getattr(scope, 'context', '') or '')
        relevant_context = _filter_context_for_trace(
            context_str, trace_path, focus
        )
        if relevant_context:
            context_parts.append(f"## {scope_name}/\n{relevant_context}")

    unified_context = "\n\n".join(context_parts)

    # Collect contracts between files in the trace
    trace_set = set(trace_path)
    relevant_contracts = []
    for contract in invariants.get("contracts", []):
        trigger = contract.get("trigger_file", "")
        coupled = contract.get("coupled_file", "")
        if trigger in trace_set and coupled in trace_set:
            relevant_contracts.append({
                "file_a": trigger,
                "file_b": coupled,
                "co_change_rate": contract.get("confidence", 0),
                "note": contract.get("description", ""),
            })

    # Collect anti-patterns relevant to trace files
    relevant_constraints = []
    for scope_name in scopes_crossed:
        scope = find_scope(scope_name, repo_root)
        if not scope:
            continue
        anti_patterns = getattr(scope, 'anti_patterns', []) or []
        for ap in anti_patterns:
            target_files = set(ap.get("scope_files") or [])
            if not target_files or target_files & trace_set:
                relevant_constraints.append({
                    "type": "anti_pattern",
                    "pattern": ap.get("pattern", ""),
                    "message": ap.get("message", ""),
                })

    # Token count
    token_count = estimate_tokens(unified_context) if unified_context else 0

    return {
        "entry_file": entry_file,
        "trace_path": trace_path,
        "scopes_crossed": scopes_crossed,
        "unified_context": unified_context,
        "relevant_contracts": relevant_contracts,
        "relevant_constraints": relevant_constraints,
        "trace_token_count": token_count,
        "depth_reached": depth_reached,
    }


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


def _get_npmi(file_a: str, file_b: str, invariants: dict) -> float:
    """Look up NPMI (co-change confidence) between two files."""
    # Try indexed lookup first
    npmi_index = invariants.get("npmi_index", {})
    if file_a in npmi_index and file_b in npmi_index[file_a]:
        return npmi_index[file_a][file_b]
    if file_b in npmi_index and file_a in npmi_index[file_b]:
        return npmi_index[file_b][file_a]

    # Fall back to linear scan
    for contract in invariants.get("contracts", []):
        t = contract.get("trigger_file", "")
        c = contract.get("coupled_file", "")
        if (t == file_a and c == file_b) or (t == file_b and c == file_a):
            return contract.get("confidence", 0)
    return 0.0


def _filter_context_for_trace(
    context: str,
    trace_files: List[str],
    focus: Optional[str],
) -> str:
    """Extract context sections relevant to the trace path."""
    if not context:
        return ""

    trace_basenames = {os.path.basename(f) for f in trace_files}
    trace_stems = {os.path.splitext(os.path.basename(f))[0] for f in trace_files}

    sections = _split_context_sections(context)
    relevant = []

    for section_name, section_text in sections:
        text_lower = section_text.lower()

        # Keep if mentions a trace file
        if any(name.lower() in text_lower for name in trace_basenames):
            relevant.append(section_text)
            continue

        # Keep if mentions a trace file stem
        if any(stem.lower() in text_lower for stem in trace_stems if len(stem) > 2):
            relevant.append(section_text)
            continue

        # Keep if matches focus keyword
        if focus and focus.lower() in text_lower:
            relevant.append(section_text)
            continue

        # Keep contracts and anti-patterns unconditionally
        section_lower = section_name.lower()
        if "contract" in section_lower or "anti-pattern" in section_lower:
            relevant.append(section_text)
            continue

    return "\n".join(relevant)


def _split_context_sections(context: str) -> List[Tuple[str, str]]:
    """Split context into (header, body) tuples by ## headers."""
    sections = []
    current_header = ""
    current_lines = []

    for line in context.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append((current_header, "\n".join(current_lines)))
            current_header = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_header, "\n".join(current_lines)))

    return sections
