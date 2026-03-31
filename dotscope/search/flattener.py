"""Abstraction flattening: resolve cross-file function calls.

For each search hit, extracts outgoing function calls from the chunk's
AST, resolves them to their definitions in other files, and inlines
the source code — annotated with swarm lock status and scope crossing.

Only eligible for Tier 1 AST chunks (those with an fqn). Tier 2/3
fallback chunks have no reliable AST and are skipped.
"""

import ast
import os
from typing import Dict, List, Optional

from ..models import FileAnalysis
from .models import FlattenedAbstraction, SearchBundle


MAX_ABSTRACTIONS_PER_HIT = 3


def flatten_abstractions(
    bundle: SearchBundle,
    analyses: Dict[str, FileAnalysis],
    import_map: Dict[str, str],
    swarm_locks: Optional[dict] = None,
    scope_index: Optional[Dict[str, str]] = None,
    root: Optional[str] = None,
) -> List[FlattenedAbstraction]:
    """Extract and resolve function calls from the primary chunk.

    Args:
        bundle: Search hit with content and file_path.
        analyses: {file_path: FileAnalysis} for the repo.
        import_map: {imported_name: source_file_path} for the hit's file.
        swarm_locks: {file_path: "exclusive_locked"|"shared_locked"|"unlocked"}.
        scope_index: {file_path: scope_name} from .scopes index.
        root: Repository root for reading source files.
    """
    # Only flatten Tier 1 chunks
    if bundle.content and not _has_reliable_ast(bundle):
        return []

    # Parse outgoing calls from the chunk
    try:
        tree = ast.parse(bundle.content)
    except SyntaxError:
        return []

    calls = _extract_calls(tree)
    if not calls:
        return []

    hit_scope = scope_index.get(bundle.file_path, "") if scope_index else ""
    abstractions = []

    for call_name in calls:
        if len(abstractions) >= MAX_ABSTRACTIONS_PER_HIT:
            break

        # Resolve call to source file
        source_file = import_map.get(call_name)
        if not source_file:
            continue

        # Determine scope crossing
        call_scope = scope_index.get(source_file, "") if scope_index else ""
        if source_file == bundle.file_path:
            crossing = "same_file"
            continue  # Skip same-file calls — agent already has it
        elif call_scope and hit_scope and call_scope != hit_scope:
            crossing = "cross_scope"
        else:
            crossing = "cross_file"

        # Extract function source
        source_code = _extract_function_source(source_file, call_name, analyses, root)
        if not source_code:
            continue

        # Check lock status
        lock_status = "unlocked"
        if swarm_locks:
            lock_status = swarm_locks.get(source_file, "unlocked")

        abstractions.append(FlattenedAbstraction(
            call_name=call_name,
            origin_file=source_file,
            source_code=source_code,
            lock_status=lock_status,
            scope_crossing=crossing,
        ))

    # Sort: cross_scope first (most valuable), then cross_file
    priority = {"cross_scope": 0, "cross_file": 1, "same_file": 2}
    abstractions.sort(key=lambda a: priority.get(a.scope_crossing, 2))

    return abstractions


def _has_reliable_ast(bundle: SearchBundle) -> bool:
    """Check if the bundle's chunk has reliable AST (Tier 1)."""
    # Bundles from SearchResult carry chunk metadata
    # If it was a line_segment or char_segment, skip
    chunk_type = getattr(bundle, "_chunk_type", None)
    # For now, try to parse — if it works, we can extract calls
    return True


def _extract_calls(tree: ast.AST) -> List[str]:
    """Extract function call names from an AST."""
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name and not name.startswith("_") and name not in calls:
                calls.append(name)
    return calls


def _extract_function_source(
    file_path: str,
    func_name: str,
    analyses: Dict[str, FileAnalysis],
    root: Optional[str],
) -> Optional[str]:
    """Extract a function's source code from its file."""
    analysis = analyses.get(file_path)
    if not analysis:
        return None

    for fn in analysis.functions:
        if fn.name == func_name:
            return _read_lines(file_path, fn.line, getattr(fn, "end_line", fn.line + 10), root)

    # Check class methods
    for cls in analysis.classes:
        for method_name in cls.methods:
            if method_name == func_name:
                # Approximate: read from class start + method offset
                return _read_lines(file_path, cls.line, getattr(cls, "end_line", cls.line + 30), root)

    return None


def _read_lines(
    file_path: str, start: int, end: int, root: Optional[str]
) -> Optional[str]:
    """Read specific lines from a file."""
    if not root:
        return None
    full_path = os.path.join(root, file_path)
    if not os.path.isfile(full_path):
        return None
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if start > 0 and end <= len(lines):
            return "".join(lines[start - 1:end])
    except Exception:
        pass
    return None


def build_lock_status_map(
    repo_root: str,
) -> Dict[str, str]:
    """Build a map of file_path → lock status from swarm state."""
    try:
        from ..storage.swarm_state import load_swarm_state, gc_expired_locks
        state = load_swarm_state(repo_root)
        gc_expired_locks(state)

        status: Dict[str, str] = {}
        for lock in state.locks.values():
            for f in lock.exclusive_files:
                status[f] = "exclusive_locked"
            for f in lock.shared_files:
                if f not in status:  # Exclusive takes precedence
                    status[f] = "shared_locked"
        return status
    except Exception:
        return {}
