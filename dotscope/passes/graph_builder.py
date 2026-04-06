"""Dependency graph analysis: AST-powered import parsing, module boundary detection.

Builds a file-level dependency graph with transitive closure support.
"""

import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ..ast_analyzer import (
    analyze_file,
    resolve_js_import,
    resolve_python_import,
)
from ..constants import LANG_MAP, SKIP_DIRS
from ..ignore import load_ignore_patterns, should_skip
from ..models.core import (
    DependencyGraph,
    FileNode,
    ModuleBoundary,
    ModuleAPI,
)
from ..paths import normalize_relative_path


def build_graph(root: str) -> DependencyGraph:
    """Build a dependency graph using AST analysis.

    1. Walk all source files
    2. AST-analyze each file for imports + API surface
    3. Resolve imports to file paths
    4. Detect module boundaries using directory cohesion
    """
    root = os.path.abspath(root)
    graph = DependencyGraph(root=root)

    source_files = _collect_source_files(root)

    # AST analyze each file
    for rel_path, language in source_files:
        abs_path = os.path.join(root, rel_path)
        api = analyze_file(abs_path, language)

        resolved_imports = []
        if api:
            graph.apis[rel_path] = api
            for imp in api.imports:
                resolved = _resolve_import(imp, rel_path, root, language)
                if resolved:
                    resolved_imports.append(resolved)
                    imp.resolved_path = resolved

        node = FileNode(
            path=rel_path,
            language=language,
            imports=resolved_imports,
            api=api,
        )
        graph.files[rel_path] = node

    # Build edge list and back-references
    for path, node in graph.files.items():
        for imp in node.imports:
            graph.edges.append((path, imp))
            if imp in graph.files:
                graph.files[imp].imported_by.append(path)

    # Polyglot Context: cross-language network edges
    build_network_edges(graph)

    graph.modules = _detect_modules(graph)
    return graph


def build_partial_graph(root: str, seed_files: List[str]) -> DependencyGraph:
    """Build a graph containing only seed_files and their direct imports.

    Used by lazy ingest to scope analysis to a single module.
    Does NOT detect module boundaries (requires the full graph).

    Args:
        root: Repository root (absolute path)
        seed_files: List of (relative_path, language) tuples
    """
    root = os.path.abspath(root)
    graph = DependencyGraph(root=root)

    # AST-analyze seed files
    for rel_path, language in seed_files:
        abs_path = os.path.join(root, rel_path)
        api = analyze_file(abs_path, language)

        resolved_imports = []
        if api:
            graph.apis[rel_path] = api
            for imp in api.imports:
                resolved = _resolve_import(imp, rel_path, root, language)
                if resolved:
                    resolved_imports.append(resolved)
                    imp.resolved_path = resolved

        node = FileNode(
            path=rel_path,
            language=language,
            imports=resolved_imports,
            api=api,
        )
        graph.files[rel_path] = node

    # Follow direct imports one level deep
    imports_to_add = []
    for path, node in graph.files.items():
        for imp in node.imports:
            if imp not in graph.files:
                imp_abs = os.path.join(root, imp)
                if os.path.exists(imp_abs):
                    ext = os.path.splitext(imp)[1]
                    lang = LANG_MAP.get(ext)
                    if lang:
                        imports_to_add.append((imp, lang))

    for rel_path, language in imports_to_add:
        abs_path = os.path.join(root, rel_path)
        api = analyze_file(abs_path, language)
        if api:
            graph.apis[rel_path] = api
        node = FileNode(
            path=rel_path,
            language=language,
            imports=[],
            api=api,
        )
        graph.files[rel_path] = node

    # Build edges
    for path, node in graph.files.items():
        for imp in node.imports:
            graph.edges.append((path, imp))
            if imp in graph.files:
                graph.files[imp].imported_by.append(path)

    return graph


def transitive_deps(graph: DependencyGraph, file: str) -> Set[str]:
    """BFS for all transitive dependencies of a file (cycle-safe)."""
    visited = set()
    queue = deque()

    node = graph.files.get(file)
    if not node:
        return visited

    for imp in node.imports:
        queue.append(imp)

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        dep_node = graph.files.get(current)
        if dep_node:
            for imp in dep_node.imports:
                if imp not in visited:
                    queue.append(imp)

    return visited


def transitive_dependents(graph: DependencyGraph, file: str) -> Set[str]:
    """BFS for all transitive dependents of a file (who ultimately depends on this)."""
    visited = set()
    queue = deque()

    node = graph.files.get(file)
    if not node:
        return visited

    for imp_by in node.imported_by:
        queue.append(imp_by)

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        dep_node = graph.files.get(current)
        if dep_node:
            for imp_by in dep_node.imported_by:
                if imp_by not in visited:
                    queue.append(imp_by)

    return visited


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _collect_source_files(root: str) -> List[Tuple[str, str]]:
    """Walk the tree and collect (relative_path, language)."""
    lang_map = {k: v.lower() for k, v in LANG_MAP.items()}
    ignore_patterns = load_ignore_patterns(root)
    results = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not should_skip(
                os.path.relpath(os.path.join(dirpath, d), root),
                SKIP_DIRS,
                ignore_patterns,
            )
        ]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in lang_map:
                rel = normalize_relative_path(os.path.relpath(os.path.join(dirpath, fn), root))
                if not should_skip(rel, frozenset(), ignore_patterns):
                    results.append((rel, lang_map[ext]))

    return sorted(results)


def _resolve_import(imp, source_file: str, root: str, language: str):
    """Resolve an import to a relative file path."""
    if language == "python":
        return resolve_python_import(imp, os.path.join(root, source_file), root)
    elif language in ("javascript", "typescript"):
        return resolve_js_import(imp, os.path.join(root, source_file), root)
    elif language == "go":
        from .lang.go import resolve_go_import
        return resolve_go_import(imp, os.path.join(root, source_file), root)
    elif language == "solidity":
        from .lang.solidity import resolve_solidity_import
        return resolve_solidity_import(imp, os.path.join(root, source_file), root)
    return None


def _detect_modules(graph: DependencyGraph) -> List[ModuleBoundary]:
    """Detect module boundaries using directory structure + import cohesion.

    Uses transitive coupling for more accurate cohesion scoring.
    """
    dir_files: Dict[str, List[str]] = defaultdict(list)
    for rel_path in graph.files:
        parts = Path(rel_path).parts
        if len(parts) > 1:
            dir_files[parts[0]].append(rel_path)

    modules = []
    for directory, files in sorted(dir_files.items()):
        file_set = set(files)
        internal = 0
        external = 0
        ext_deps: Set[str] = set()
        dep_by: Set[str] = set()

        for f in files:
            # Use transitive deps for richer cohesion
            all_deps = transitive_deps(graph, f)
            for dep in all_deps:
                if dep in file_set:
                    internal += 1
                else:
                    external += 1
                    dep_parts = Path(dep).parts
                    if len(dep_parts) > 1:
                        ext_deps.add(dep_parts[0])

            all_dependents = transitive_dependents(graph, f)
            for dep_by_file in all_dependents:
                if dep_by_file not in file_set:
                    dep_parts = Path(dep_by_file).parts
                    if len(dep_parts) > 1:
                        dep_by.add(dep_parts[0])

        total = internal + external
        cohesion = internal / total if total > 0 else 1.0

        modules.append(ModuleBoundary(
            directory=directory,
            files=files,
            internal_edges=internal,
            external_edges=external,
            external_deps=sorted(ext_deps - {directory}),
            depended_on_by=sorted(dep_by - {directory}),
            cohesion=round(cohesion, 3),
        ))

    modules.sort(key=lambda m: -len(m.files))
    return modules


def format_graph_summary(graph: DependencyGraph) -> str:
    """Human-readable summary of the dependency graph."""
    lines = [
        f"Dependency Graph: {len(graph.files)} files, {len(graph.edges)} edges",
        f"Detected {len(graph.modules)} module(s):",
        "",
    ]

    for mod in graph.modules:
        cohesion_bar = "█" * int(mod.cohesion * 10) + "░" * (10 - int(mod.cohesion * 10))
        lines.append(
            f"  {mod.directory}/ — {len(mod.files)} files, "
            f"cohesion: {cohesion_bar} {mod.cohesion:.0%}"
        )
        if mod.external_deps:
            lines.append(f"    depends on: {', '.join(mod.external_deps)}")
        if mod.depended_on_by:
            lines.append(f"    used by: {', '.join(mod.depended_on_by)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Polyglot Context: cross-language network edge builder
# ---------------------------------------------------------------------------

def build_network_edges(graph: DependencyGraph) -> None:
    """Draw edges between files containing matching endpoints and consumers.

    Populates ``graph.network_edges`` (provider → consumer) and
    ``graph.reverse_network_edges`` (consumer → provider list) for O(1)
    lookups in both directions.
    """
    from collections import defaultdict

    # Collect providers and consumers from AST data
    providers = []  # (file_path, NetworkEndpoint)
    consumers = []  # (file_path, NetworkConsumer)

    for path, api in graph.apis.items():
        for ep in getattr(api, "network_endpoints", []):
            providers.append((path, ep))
        for cons in getattr(api, "network_consumers", []):
            consumers.append((path, cons))

    if not providers or not consumers:
        return

    # Match providers to consumers
    forward: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    reverse: Dict[str, list] = defaultdict(list)

    # Confidence dict: { (provider_file, consumer_file): max_confidence }
    confidence_map: Dict[tuple, float] = {}

    for p_path, ep in providers:
        for c_path, cons in consumers:
            if p_path == c_path:
                continue  # Same file — skip self-edges
            if not _methods_match(ep.method, cons.method):
                continue
            conf = _routes_match_confidence(ep, cons)
            if conf > 0:
                forward[p_path][c_path].append(ep)
                key = (p_path, c_path)
                confidence_map[key] = max(confidence_map.get(key, 0), conf)

    # Build reverse lookup
    for p_path, consumer_dict in forward.items():
        for c_path in consumer_dict:
            if p_path not in reverse.get(c_path, []):
                reverse[c_path].append(p_path)

    graph.network_edges = dict(forward)
    graph.reverse_network_edges = dict(reverse)
    graph.network_confidence = confidence_map


def _methods_match(provider_method: str, consumer_method: str) -> bool:
    """Check if HTTP methods are compatible."""
    if provider_method == "ALL" or consumer_method == "ALL":
        return True
    return provider_method.upper() == consumer_method.upper()


def _routes_match_confidence(ep, cons) -> float:
    """Score how confidently a provider endpoint matches a consumer call.

    Returns:
        1.0 — exact regex match (provider's regex matches consumer's path)
        0.8 — suffix-aligned match (base URL stripped)
        0.5 — ViewSet semantic root substring match
        0.0 — no match
    """
    import re

    # Primary: provider regex matches consumer raw path → confidence 1.0
    try:
        if ep.regex_path and re.match(ep.regex_path, cons.raw_path):
            return 1.0
    except re.error:
        pass

    # Reverse: consumer regex matches provider raw path → confidence 1.0
    try:
        if getattr(cons, "regex_path", "") and re.match(cons.regex_path, ep.raw_path):
            return 1.0
    except re.error:
        pass

    # Fallback: suffix alignment for base URL differences → confidence 0.8
    if _paths_fuzzy_match(ep.raw_path, cons.raw_path):
        return 0.8

    # ViewSet semantic matching: "DocumentTypeViewSet" → "documenttype"
    # matches consumer "/api/document-types/" → confidence 0.5
    if getattr(ep, "handler_name", "") and "ViewSet" in ep.handler_name:
        semantic_root = ep.handler_name.replace("ViewSet", "").lower()
        if semantic_root:
            normalized = re.sub(r"[-_]", "", cons.raw_path.lower())
            if semantic_root in normalized:
                return 0.5

    return 0.0


def _paths_fuzzy_match(provider_path: str, consumer_path: str) -> bool:
    """Suffix-aligned fuzzy match for paths with different base URLs.

    Handles the case where Python exports ``/api/v1/users`` and
    JS calls ``apiClient.get('/users')`` with a base URL prefix.
    """
    # Normalize: strip trailing slashes
    p = provider_path.rstrip("/")
    c = consumer_path.rstrip("/")

    if p == c:
        return True

    # Strip common API prefixes and try suffix match
    prefixes = ["/api/v1", "/api/v2", "/api"]
    for prefix in prefixes:
        stripped = p[len(prefix):] if p.startswith(prefix) else p
        if stripped == c or c == stripped:
            return True

    # Suffix alignment: does the consumer path match the tail of the provider path?
    p_parts = p.split("/")
    c_parts = c.split("/")
    if len(c_parts) <= len(p_parts):
        if p_parts[-len(c_parts):] == c_parts:
            return True

    return False
