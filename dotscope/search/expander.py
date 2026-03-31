"""Dependency expansion for search hits.

Expands top search results with their architectural neighborhood:
network consumers/providers, NPMI co-change companions, and test files.
"""

import os
from typing import Dict, List, Optional, Set

from .models import ExpandedContext, SearchBundle, SearchResult

# Caps per result
MAX_EXPANSION_PER_HIT = 8
MAX_NPMI_COMPANIONS = 3
MAX_TEST_COMPANIONS = 2

# NPMI threshold for companion inclusion
NPMI_THRESHOLD = 0.5


def expand_search_hits(
    top_results: List[SearchResult],
    network_edges: Optional[Dict[str, Dict[str, list]]] = None,
    reverse_network_edges: Optional[Dict[str, List[str]]] = None,
    npmi_index: Optional[Dict[str, Dict[str, float]]] = None,
    root: Optional[str] = None,
) -> List[SearchBundle]:
    """Expand top search hits with their architectural neighborhood.

    Only expands the top 3 results. Deduplication across all results
    (a file appears at most once in the expansion set).
    """
    seen_files: Set[str] = set()
    bundles = []

    for result in top_results[:3]:
        seen_files.add(result.file_path)

        expanded = ExpandedContext()
        expansion_count = 0

        # 1. Network edges (Polyglot Context)
        if network_edges and result.file_path in network_edges:
            for consumer in network_edges[result.file_path]:
                if consumer not in seen_files and expansion_count < MAX_EXPANSION_PER_HIT:
                    expanded.network_consumers.append(consumer)
                    seen_files.add(consumer)
                    expansion_count += 1

        if reverse_network_edges and result.file_path in reverse_network_edges:
            for provider in reverse_network_edges[result.file_path]:
                if provider not in seen_files and expansion_count < MAX_EXPANSION_PER_HIT:
                    expanded.network_providers.append(provider)
                    seen_files.add(provider)
                    expansion_count += 1

        # 2. NPMI companions
        if npmi_index and result.file_path in npmi_index:
            partners = sorted(
                npmi_index[result.file_path].items(),
                key=lambda x: -x[1],
            )
            for partner, npmi in partners[:MAX_NPMI_COMPANIONS]:
                if npmi >= NPMI_THRESHOLD and partner not in seen_files and expansion_count < MAX_EXPANSION_PER_HIT:
                    expanded.npmi_companions.append(partner)
                    seen_files.add(partner)
                    expansion_count += 1

        # 3. Test companions
        test_files = _find_test_companions(result.file_path, npmi_index, root)
        for tf in test_files[:MAX_TEST_COMPANIONS]:
            if tf not in seen_files and expansion_count < MAX_EXPANSION_PER_HIT:
                expanded.test_companions.append(tf)
                seen_files.add(tf)
                expansion_count += 1

        bundles.append(SearchBundle(
            file_path=result.file_path,
            score=result.recency_adjusted,
            content=result.chunk.content,
            expanded=expanded,
        ))

    return bundles


def _find_test_companions(
    file_path: str,
    npmi_index: Optional[Dict[str, Dict[str, float]]],
    root: Optional[str],
) -> List[str]:
    """Find test files for a source file.

    Two strategies:
      1. NPMI-based: test files with co-change affinity > NPMI_THRESHOLD
      2. Naming convention: test_{filename}.py or {filename}_test.py
    """
    companions = []

    # NPMI-based
    if npmi_index and file_path in npmi_index:
        for partner, npmi in npmi_index[file_path].items():
            if npmi >= NPMI_THRESHOLD and "test" in partner.lower():
                companions.append(partner)

    # Naming convention
    basename = os.path.basename(file_path)
    name, ext = os.path.splitext(basename)
    test_names = [f"test_{name}{ext}", f"{name}_test{ext}"]

    if root:
        # Search in tests/ directory
        tests_dir = os.path.join(root, "tests")
        if os.path.isdir(tests_dir):
            for tn in test_names:
                candidate = os.path.join("tests", tn)
                if os.path.isfile(os.path.join(root, candidate)):
                    if candidate not in companions:
                        companions.append(candidate)

        # Search in same directory
        file_dir = os.path.dirname(file_path)
        for tn in test_names:
            candidate = os.path.join(file_dir, tn) if file_dir else tn
            if root and os.path.isfile(os.path.join(root, candidate)):
                if candidate not in companions:
                    companions.append(candidate)

    return companions
