"""Compiled Retrieval synthesizer: all 5 stages → ResolvedScope.

Orchestrates: base retrieval → recency re-rank → dependency expansion →
abstraction flattening → compiled resolution. Single call, single
response, every signal integrated from the start.
"""

import os
from typing import Dict, List, Optional

from ..models import ResolvedScope
from .models import SearchBundle, SearchResult


def synthesize_search(
    query: str,
    root: str,
    budget: int = 8000,
    limit: int = 10,
    artifact_only: bool = False,
    task_type: Optional[str] = None,
    no_observe: bool = False,
) -> ResolvedScope:
    """The main entry point. Orchestrates all 5 stages.

    Returns a ResolvedScope enriched with retrieval provenance,
    flattened abstractions, constraints, and lock annotations.
    """
    from .retriever import search, check_index_freshness
    from .reranker import apply_recency_rerank
    from .expander import expand_search_hits
    from .flattener import flatten_abstractions, build_lock_status_map

    # Stage 1: Base retrieval
    raw_results = search(query, root, limit=limit)
    if not raw_results:
        return ResolvedScope(
            retrieval_metadata={"query": query, "results_count": 0},
        )

    # Filter artifact-only if requested
    if artifact_only:
        raw_results = [r for r in raw_results if r.chunk.chunk_type == "artifact"]
        if not raw_results:
            return ResolvedScope(
                retrieval_metadata={"query": query, "results_count": 0,
                                    "note": "No artifact chunks matched"},
            )

    # Log retrieval for observation loop
    if not no_observe:
        try:
            from .observation import log_retrieval, get_session_id
            log_retrieval(
                root,
                session_id=get_session_id(),
                query=query,
                returned_files=[r.file_path for r in raw_results],
                returned_scores={r.file_path: r.rrf_score for r in raw_results},
            )
        except Exception:
            pass

    # Stage 2: Recency re-ranking
    file_histories = _load_file_histories(root)
    ranked_results = apply_recency_rerank(raw_results, file_histories)

    # Stage 3: Dependency expansion (top 3 only)
    network_edges, reverse_edges = _load_network_edges(root)
    npmi_index = _load_npmi_index(root)
    bundles = expand_search_hits(
        ranked_results[:3],
        network_edges=network_edges,
        reverse_network_edges=reverse_edges,
        npmi_index=npmi_index,
        root=root,
    )

    # Stage 4: Abstraction flattening (top 3 only)
    analyses = _load_analyses(root)
    lock_status = build_lock_status_map(root)
    scope_index = _build_scope_index(root)

    for bundle in bundles:
        import_map = _build_import_map(bundle.file_path, analyses)
        bundle.abstractions = flatten_abstractions(
            bundle, analyses, import_map,
            swarm_locks=lock_status,
            scope_index=scope_index,
            root=root,
        )

    # Stage 5: Compiled resolution
    is_fresh, freshness_msg = check_index_freshness(root)

    # Collect all files (primary + expanded)
    all_files = []
    for bundle in bundles:
        all_files.append(bundle.file_path)
        all_files.extend(bundle.expanded.network_consumers)
        all_files.extend(bundle.expanded.network_providers)
        all_files.extend(bundle.expanded.npmi_companions)
        all_files.extend(bundle.expanded.test_companions)

    # Deduplicate preserving order
    seen = set()
    unique_files = []
    for f in all_files:
        if f not in seen:
            unique_files.append(f)
            seen.add(f)

    # Build context from scope contexts
    context_parts = []
    try:
        from ..composer import compose_for_task
        composed = compose_for_task(query, root=root, max_scopes=2)
        if composed.context:
            context_parts.append(composed.context)
    except Exception:
        pass

    # Build flattened abstractions dict
    flat_abstractions = {}
    for bundle in bundles:
        for ab in bundle.abstractions:
            flat_abstractions[ab.call_name] = {
                "origin_file": ab.origin_file,
                "source_code": ab.source_code,
                "lock_status": ab.lock_status,
                "scope_crossing": ab.scope_crossing,
            }

    # Build constraints (keep structured for JSON response)
    structured_constraints = []
    try:
        from ..passes.sentinel.constraints import build_constraints
        raw_constraints = build_constraints(root, unique_files, query)
        if raw_constraints:
            structured_constraints = raw_constraints
            constraint_lines = []
            for c in raw_constraints:
                msg = c.get("message", "")
                if msg:
                    constraint_lines.append(f"- {msg}")
            constraints_text = "\n".join(constraint_lines)
            if constraints_text:
                context_parts.append(f"\n## Constraints\n{constraints_text}")
    except Exception:
        pass

    # Build routing guidance
    structured_routing = []
    try:
        from ..passes.sentinel.constraints import build_routing_guidance
        structured_routing = build_routing_guidance(root, unique_files, query) or []
    except Exception:
        pass

    # Budget allocation: inside-out truncation
    from ..tokens import estimate_tokens
    used = 0
    budget_files = []
    for f in unique_files:
        file_tokens = estimate_tokens(f)
        if used + file_tokens <= budget:
            budget_files.append(f)
            used += file_tokens
        else:
            break

    resolved = ResolvedScope(
        files=budget_files,
        context="\n\n".join(context_parts) if context_parts else "",
        token_estimate=used,
        truncated=len(budget_files) < len(unique_files),
        constraints=structured_constraints,
        routing=structured_routing,
        flattened_abstractions=flat_abstractions,
        retrieval_metadata={
            "query": query,
            "results_count": len(ranked_results),
            "index_freshness": "fresh" if is_fresh else "stale",
            "freshness_detail": freshness_msg,
            "dense_available": any(r.dense_score > 0 for r in ranked_results),
            "expanded_files": len(unique_files),
            "budget_used": used,
            "budget_limit": budget,
        },
    )

    # Generate action hints
    try:
        from ..passes.hint_generator import generate_action_hints
        resolved.action_hints = generate_action_hints(
            resolved,
            npmi_index=npmi_index,
            network_edges=network_edges,
        )
    except Exception:
        pass

    return resolved


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_file_histories(root: str) -> Dict[str, dict]:
    """Load cached file histories for recency re-ranking."""
    try:
        from ..storage.cache import load_cached_history
        history = load_cached_history(root)
        if not history:
            return {}
        result = {}
        for fh in getattr(history, "file_histories", {}).values():
            result[fh.path] = {
                "stability": getattr(fh, "stability", ""),
                "last_modified": getattr(fh, "last_modified", 0),
            }
        return result
    except Exception:
        return {}


def _load_network_edges(root: str):
    """Load cached network edges."""
    try:
        from ..storage.cache import load_cached_network_edges
        edges = load_cached_network_edges(root)
        # Build reverse map
        reverse = {}
        for provider, consumers in edges.items():
            for consumer in consumers:
                if consumer not in reverse:
                    reverse[consumer] = []
                reverse[consumer].append(provider)
        return edges, reverse
    except Exception:
        return {}, {}


def _load_npmi_index(root: str) -> Dict[str, Dict[str, float]]:
    """Load cached NPMI co-change index."""
    import json
    from pathlib import Path
    path = Path(root) / ".dotscope" / "cache" / "npmi_index.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_analyses(root: str) -> Dict[str, "FileAnalysis"]:
    """Load cached FileAnalysis objects (from graph APIs)."""
    try:
        from ..storage.cache import load_cached_graph_hubs
        # Graph hubs don't carry full FileAnalysis, but we can
        # return empty for now — full analysis loading is for Phase 7
        return {}
    except Exception:
        return {}


def _build_import_map(
    file_path: str,
    analyses: Dict[str, "FileAnalysis"],
) -> Dict[str, str]:
    """Build {imported_name: source_file_path} for a specific file."""
    analysis = analyses.get(file_path)
    if not analysis:
        return {}
    result = {}
    for imp in getattr(analysis, "imports", []):
        if imp.resolved_path:
            for name in imp.names:
                result[name] = imp.resolved_path
    return result


def _build_scope_index(root: str) -> Dict[str, str]:
    """Build {file_path: scope_name} from the .scopes index."""
    try:
        from ..discovery import find_all_scopes
        from ..parser import parse_scope_file
        index = {}
        for sf in find_all_scopes(root):
            try:
                config = parse_scope_file(sf)
                name = os.path.basename(os.path.dirname(config.path)) or "root"
                for inc in config.includes:
                    index[inc] = name
            except Exception:
                continue
        return index
    except Exception:
        return {}
