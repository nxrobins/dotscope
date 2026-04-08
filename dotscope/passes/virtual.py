"""Virtual scopes: cross-cutting concern detection from import graph hubs.

Directory scopes capture physical structure. Virtual scopes capture logical
architecture — a User lifecycle spanning models/, auth/, validators/, serializers/.

Detection algorithm:
1. Find hub files (imported by 3+ files from 2+ directories)
2. Collect cluster (hub + importers + shared imports within 1 hop)
3. Filter by cohesion (more internal edges than external)
4. Name by centrality (most-imported symbol)
5. Deduplicate overlapping clusters (>70% overlap → merge)
"""

import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..engine.context import parse_context
from ..models.core import DependencyGraph
from ..models.core import ScopeConfig
from ..models.passes import VirtualScope  # noqa: F401
from ..paths import make_relative, normalize_relative_path, normalize_scope_ref
from ..engine.tokens import estimate_scope_tokens

# Utility directories whose files connect everything (not meaningful clusters)
_UTILITY_DIRS = {"utils", "helpers", "common", "shared", "lib", "core"}


def virtual_scope_directory(name: str) -> str:
    """Return the canonical directory for a virtual scope."""
    return normalize_relative_path(f"virtual/{name}")


def detect_virtual_scopes(
    graph: DependencyGraph,
    min_importers: int = 3,
    min_directories: int = 2,
    min_cohesion: float = 0.3,
) -> List[ScopeConfig]:
    """Detect cross-cutting concerns from the import graph.

    Returns ScopeConfig objects for virtual scopes, ready to be
    added to the ingest plan alongside directory scopes.
    """
    root = graph.root
    hubs = _find_hubs(graph, min_importers, min_directories)
    clusters = [_build_cluster(hub, graph) for hub in hubs]
    clusters = [c for c in clusters if c.cohesion >= min_cohesion]
    clusters = _deduplicate(clusters)

    scopes = []
    for cluster in clusters:
        config = _cluster_to_scope(cluster, root)
        if config:
            scopes.append(config)

    return scopes


def _find_hubs(
    graph: DependencyGraph, min_importers: int, min_dirs: int
) -> List[str]:
    """Find files imported by 3+ files from 2+ different directories."""
    hubs = []
    for path, node in graph.files.items():
        if not node.imported_by:
            continue

        # Skip utility directories
        parts = Path(path).parts
        if len(parts) > 1 and parts[0].lower() in _UTILITY_DIRS:
            continue

        importer_dirs = set()
        for imp_by in node.imported_by:
            imp_parts = Path(imp_by).parts
            if len(imp_parts) > 1:
                importer_dirs.add(imp_parts[0])

        if len(node.imported_by) >= min_importers and len(importer_dirs) >= min_dirs:
            hubs.append(path)

    return hubs


def _build_cluster(hub: str, graph: DependencyGraph) -> VirtualScope:
    """Build a cluster around a hub file.

    Cluster = hub + all importers + shared imports within 1 hop.
    """
    hub_node = graph.files.get(hub)
    if not hub_node:
        return VirtualScope(name="", hub_file=hub, files=[], cohesion=0, directories_spanned=0)

    cluster_files: Set[str] = {hub}
    cluster_files.update(hub_node.imported_by)

    # Add shared imports (files that multiple importers also import)
    import_counts: Dict[str, int] = defaultdict(int)
    for importer in hub_node.imported_by:
        imp_node = graph.files.get(importer)
        if imp_node:
            for dep in imp_node.imports:
                if dep != hub and dep not in cluster_files:
                    import_counts[dep] += 1

    # Only add shared imports that 2+ importers share
    for dep, count in import_counts.items():
        if count >= 2:
            cluster_files.add(dep)

    # Compute cohesion
    internal_edges = 0
    external_edges = 0
    for f in cluster_files:
        node = graph.files.get(f)
        if not node:
            continue
        for imp in node.imports:
            if imp in cluster_files:
                internal_edges += 1
            else:
                external_edges += 1

    total = internal_edges + external_edges
    cohesion = internal_edges / total if total > 0 else 0.0

    # Count directories spanned
    dirs = set()
    for f in cluster_files:
        parts = Path(f).parts
        if len(parts) > 1:
            dirs.add(parts[0])

    # Name from hub file
    name = _infer_name(hub, graph)

    return VirtualScope(
        name=name,
        hub_file=hub,
        files=sorted(cluster_files),
        cohesion=round(cohesion, 3),
        directories_spanned=len(dirs),
    )


def _infer_name(hub: str, graph: DependencyGraph) -> str:
    """Infer a name for the virtual scope from the hub file."""
    basename = os.path.splitext(os.path.basename(hub))[0]
    # e.g., "models/user.py" → "user_lifecycle"
    if basename in ("__init__", "index"):
        parts = Path(hub).parts
        if len(parts) > 1:
            basename = parts[-2]
    return f"{basename}_lifecycle"


def _deduplicate(clusters: List[VirtualScope]) -> List[VirtualScope]:
    """Merge clusters with >70% file overlap."""
    if len(clusters) <= 1:
        return clusters

    result = []
    merged = set()

    for i, a in enumerate(clusters):
        if i in merged:
            continue
        best = a
        for j, b in enumerate(clusters):
            if j <= i or j in merged:
                continue
            a_set = set(a.files)
            b_set = set(b.files)
            overlap = len(a_set & b_set) / len(a_set | b_set) if (a_set | b_set) else 0
            if overlap > 0.7:
                # Keep the one with more files
                if len(b.files) > len(best.files):
                    best = b
                merged.add(j)
        result.append(best)

    return result


def _cluster_to_scope(cluster: VirtualScope, root: str) -> Optional[ScopeConfig]:
    """Convert a virtual scope cluster to a ScopeConfig."""
    if not cluster.files or not cluster.name:
        return None

    description = (
        f"Virtual scope: {cluster.name} "
        f"(spans {cluster.directories_spanned} modules, "
        f"hub: {cluster.hub_file})"
    )

    dirs_spanned = set()
    for f in cluster.files:
        parts = Path(f).parts
        if len(parts) > 1:
            dirs_spanned.add(parts[0])

    context = parse_context(
        f"Cross-cutting concern detected from import graph.\n"
        f"Hub file: {cluster.hub_file} "
        f"(imported by {len(cluster.files) - 1} files across "
        f"{cluster.directories_spanned} modules)\n"
        f"\n"
        f"Directories spanned: {', '.join(sorted(dirs_spanned))}\n"
        f"Cohesion: {cluster.cohesion:.0%}"
    )

    full_paths = [os.path.join(root, f) for f in cluster.files]
    token_est = estimate_scope_tokens(full_paths)

    related = [f"{d}/.scope" for d in sorted(dirs_spanned)]
    related = [normalize_scope_ref(path) for path in related]
    scope_dir = virtual_scope_directory(cluster.name)

    return ScopeConfig(
        path=os.path.join(root, scope_dir.replace("/", os.sep), ".scope"),
        description=description,
        includes=cluster.files,
        excludes=[],
        context=context,
        related=related,
        tags=["virtual", "cross-cutting", cluster.name.replace("_lifecycle", "")],
        tokens_estimate=token_est,
    )


def format_virtual_scopes(scopes: List[ScopeConfig], root: str) -> str:
    """Human-readable summary of detected virtual scopes."""
    if not scopes:
        return "No cross-cutting virtual scopes detected."

    lines = [f"Detected {len(scopes)} virtual scope(s):", ""]
    for scope in scopes:
        lines.append(f"  {make_relative(scope.path, root)}")
        lines.append(f"    {scope.description}")
        lines.append(f"    files: {len(scope.includes)}, ~{scope.tokens_estimate:,} tokens")
        if scope.related:
            lines.append(f"    related: {', '.join(scope.related)}")
        lines.append("")

    return "\n".join(lines)
