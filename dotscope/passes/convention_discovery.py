"""Convention discovery: mine structural patterns from AST data."""

import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from ..models import ConventionRule, DependencyGraph, FileAnalysis, HistoryAnalysis


def discover_conventions(
    ast_data: Dict[str, FileAnalysis],
    graph: DependencyGraph,
    history: Optional[HistoryAnalysis] = None,
) -> List[ConventionRule]:
    """Mine structural patterns that repeat across files.

    Uses multi-pass clustering to avoid grouping only by directory:
      Pass 1: Group by shared decorators (e.g., all @app.route files)
      Pass 2: Group by shared base classes (e.g., all BaseModel subclasses)
      Pass 3: Group by shared suffix/prefix (e.g., *_repo.py)

    Cross-cutting conventions (decorator-based, base-class-based) are
    discovered before directory-based ones. A file can match multiple
    passes — deduplication happens after all passes complete.
    """
    conventions = []
    claimed_files: Set[str] = set()

    # Pass 1: Shared decorators (strongest signal, survives refactors)
    decorator_groups: Dict[str, List[Tuple[str, FileAnalysis]]] = defaultdict(list)
    for path, analysis in ast_data.items():
        for dec in (analysis.decorators_used or []):
            normalized = _normalize_decorator(dec)
            decorator_groups[normalized].append((path, analysis))

    for dec, files in decorator_groups.items():
        if len(files) >= 3:
            conv = _build_convention_from_group(
                files, graph, signal_type="decorator", signal_value=dec
            )
            if conv:
                conventions.append(conv)
                claimed_files.update(f[0] for f in files)

    # Pass 2: Shared base classes
    base_groups: Dict[str, List[Tuple[str, FileAnalysis]]] = defaultdict(list)
    for path, analysis in ast_data.items():
        if path in claimed_files:
            continue
        for cls in (analysis.classes or []):
            for base in (cls.bases or []):
                base_groups[base].append((path, analysis))

    for base, files in base_groups.items():
        if len(files) >= 3:
            conv = _build_convention_from_group(
                files, graph, signal_type="base_class", signal_value=base
            )
            if conv:
                conventions.append(conv)
                claimed_files.update(f[0] for f in files)

    # Pass 3: Shared suffix/prefix (weakest signal, path-dependent)
    suffix_groups: Dict[str, List[Tuple[str, FileAnalysis]]] = defaultdict(list)
    for path, analysis in ast_data.items():
        if path in claimed_files:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        for suffix in _extract_suffixes(stem):
            suffix_groups[suffix].append((path, analysis))

    for suffix, files in suffix_groups.items():
        if len(files) >= 3:
            conv = _build_convention_from_group(
                files, graph, signal_type="suffix", signal_value=suffix
            )
            if conv:
                conventions.append(conv)

    # Pass 4: Spatial centroid — discover dominant directory pattern per convention
    from .convention_parser import matches_convention

    for conv in conventions:
        matched = [
            p for p, a in ast_data.items()
            if matches_convention(a, p, conv.match_criteria)
        ]
        centroid = discover_spatial_centroid(matched)
        if centroid:
            conv.rules["allowed_paths"] = [centroid]

    return conventions


def _normalize_decorator(dec: str) -> str:
    """Normalize a decorator string for grouping.

    '@app.route("/users")' -> 'app.route'
    '@router.get' -> 'router.get'
    """
    dec = dec.lstrip("@")
    # Strip arguments
    paren = dec.find("(")
    if paren != -1:
        dec = dec[:paren]
    return dec.strip()


def _extract_suffixes(stem: str) -> List[str]:
    """Extract meaningful suffixes from a filename stem.

    "user_controller" -> ["_controller"]
    "billing_repo" -> ["_repo"]
    """
    known = (
        "_controller", "_service", "_repo", "_repository",
        "_handler", "_manager", "_factory", "_helper",
        "_view", "_model", "_test", "_middleware",
    )
    result = []
    for suffix in known:
        if stem.endswith(suffix):
            result.append(suffix)
    return result


def _build_convention_from_group(
    files: List[Tuple[str, FileAnalysis]],
    graph: DependencyGraph,
    signal_type: str,
    signal_value: str,
) -> Optional[ConventionRule]:
    """Build a ConventionRule from a group of files sharing a structural trait."""
    paths = [f[0] for f in files]
    analyses = [f[1] for f in files]

    match_criteria = _derive_match_criteria(paths, analyses, signal_type, signal_value)
    if not match_criteria:
        return None

    rules = _derive_rules(paths, analyses, graph)
    name = _derive_name(signal_type, signal_value)

    return ConventionRule(
        name=name,
        source="discovered",
        match_criteria=match_criteria,
        rules=rules,
        description=f"Discovered from {len(files)} files sharing {signal_type}: {signal_value}",
        compliance=1.0,
    )


def _derive_name(signal_type: str, signal_value: str) -> str:
    """Generate a human-readable convention name."""
    if signal_type == "decorator":
        # "@app.route" -> "Route Handler"
        parts = signal_value.split(".")
        name = parts[-1] if parts else signal_value
        return name.replace("_", " ").title()
    elif signal_type == "base_class":
        return f"{signal_value} Subclass"
    elif signal_type == "suffix":
        # "_controller" -> "Controller"
        return signal_value.lstrip("_").replace("_", " ").title()
    return signal_value


def _derive_match_criteria(
    paths: List[str],
    analyses: List[FileAnalysis],
    signal_type: str,
    signal_value: str,
) -> dict:
    """Find common structural traits across files sharing a fingerprint."""
    any_of = []
    all_of = []

    # Primary signal goes into any_of
    if signal_type == "decorator":
        any_of.append({"has_decorator": re.escape(signal_value)})
    elif signal_type == "base_class":
        any_of.append({"base_class": signal_value})
    elif signal_type == "suffix":
        pattern = f".*{re.escape(signal_value)}\\.py"
        any_of.append({"file_path": pattern})

    # Common directory as secondary hint
    dirs = set(os.path.dirname(p) for p in paths)
    if len(dirs) == 1:
        dir_pattern = re.escape(dirs.pop()) + "/.*\\.py"
        any_of.append({"file_path": dir_pattern})

    criteria = {}
    if any_of:
        criteria["any_of"] = any_of
    if all_of:
        criteria["all_of"] = all_of
    return criteria


def _derive_rules(
    paths: List[str],
    analyses: List[FileAnalysis],
    graph: DependencyGraph,
) -> dict:
    """Find universal behavioral patterns (potential rules)."""
    rules = {}

    # Universal methods (all files implement these)
    if all(a.classes for a in analyses):
        all_methods = [
            set(a.classes[0].methods)
            for a in analyses if a.classes
        ]
        if all_methods:
            common_methods = set.intersection(*all_methods)
            required = sorted(m for m in common_methods if not m.startswith("_"))
            if required:
                rules["required_methods"] = required

    # Universal non-imports (no file imports these)
    all_imports: Set[str] = set()
    for a in analyses:
        for imp in (a.imports or []):
            if imp.module:
                all_imports.add(imp.module)

    # Check against all imports in codebase to find conspicuous absences
    all_codebase_imports: Set[str] = set()
    for node in graph.files.values():
        for imp_path in (node.imports or []):
            # Extract module name from path
            module = os.path.splitext(os.path.basename(imp_path))[0] if imp_path else ""
            if module:
                all_codebase_imports.add(module)

    common_absences = all_codebase_imports - all_imports
    if common_absences:
        frequent_elsewhere = [
            imp for imp in common_absences
            if _import_frequency(imp, graph) >= 3
        ]
        if frequent_elsewhere:
            rules["prohibited_imports"] = sorted(frequent_elsewhere[:5])

    return rules


def _import_frequency(module: str, graph: DependencyGraph) -> int:
    """Count how many files import a given module."""
    count = 0
    for node in graph.files.values():
        for imp_path in (node.imports or []):
            if module in imp_path:
                count += 1
                break
    return count


# ---------------------------------------------------------------------------
# Spatial Concierge: Centroid Discovery
# ---------------------------------------------------------------------------

from collections import Counter


def discover_spatial_centroid(
    convention_files: List[str],
) -> Optional[str]:
    """Find the dominant directory pattern for a convention.

    If 80% of files matching a convention share a directory structure,
    that structure becomes the ``allowed_paths`` regex.

    Returns a regex string or None.
    """
    if not convention_files:
        return None

    # Extract directory paths
    dirs = [os.path.dirname(f) for f in convention_files]

    # Group by exact directory
    dir_counts = Counter(dirs)
    most_common_dir, count = dir_counts.most_common(1)[0]

    if count / len(convention_files) >= 0.8:
        # 80% consensus on exact directory
        return f"{re.escape(most_common_dir)}/.*\\.py"

    # If no exact match, look for structural consensus (e.g., Domain-Driven)
    domain_pattern = _extract_domain_pattern(dirs)
    if domain_pattern:
        return domain_pattern

    return None


def _extract_domain_pattern(dirs: List[str]) -> Optional[str]:
    """Detect structural patterns like ``domains/*/api/``.

    Splits each directory path into segments, aligns them by position,
    and replaces segments with > 20% variation with ``[^/]+`` wildcards.
    Requires 80% consensus on the overall structural pattern.
    """
    if not dirs or len(dirs) < 3:
        return None

    # Split into segments
    splits = [d.split("/") for d in dirs if d]
    if not splits:
        return None

    # All paths must have the same depth for structural matching
    lengths = [len(s) for s in splits]
    length_counts = Counter(lengths)
    dominant_len, dominant_count = length_counts.most_common(1)[0]

    if dominant_count / len(splits) < 0.8:
        return None  # No consensus on depth

    # Filter to paths with the dominant depth
    aligned = [s for s in splits if len(s) == dominant_len]
    if len(aligned) < 3:
        return None

    # Build pattern: literal where all agree, wildcard where they differ
    pattern_parts = []
    for pos in range(dominant_len):
        segments_at_pos = [s[pos] for s in aligned]
        seg_counts = Counter(segments_at_pos)
        top_seg, top_count = seg_counts.most_common(1)[0]

        if top_count / len(aligned) >= 0.8:
            pattern_parts.append(re.escape(top_seg))
        else:
            pattern_parts.append("[^/]+")

    # Must have at least one wildcard to be a useful domain pattern
    if "[^/]+" not in pattern_parts:
        return None

    return "/".join(pattern_parts) + "/.*\\.py"
