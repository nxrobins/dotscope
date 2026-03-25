"""Ingest: reverse-engineer .scope files from an existing codebase.

Orchestrates graph analysis, git history mining, and doc absorption
to produce complete .scope files for every detected module boundary.

This is how dotscope enters any codebase — not by asking humans to write
.scope files, but by inferring them from signals already in the code.
"""


import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from .absorber import AbsorptionResult, absorb_docs
from .context import parse_context
from .graph import DependencyGraph, ModuleBoundary, build_graph
from .history import HistoryAnalysis, analyze_history
from .models import ScopeConfig, ScopesIndex, ScopeEntry
from .parser import serialize_scope
from .tokens import estimate_scope_tokens


@dataclass
class IngestPlan:
    """Plan for .scope files to be created."""
    root: str
    scopes: List["PlannedScope"] = field(default_factory=list)
    index: Optional[ScopesIndex] = None
    graph_summary: str = ""
    history_summary: str = ""
    backtest_summary: str = ""


@dataclass
class PlannedScope:
    """A .scope file to be created."""
    directory: str  # Relative to root
    config: ScopeConfig
    confidence: float  # How confident we are in this scope boundary
    signals: List[str]  # What signals contributed to this scope


def ingest(
    root: str,
    mine_history: bool = True,
    absorb: bool = True,
    synthesize: bool = True,
    max_commits: int = 500,
    dry_run: bool = False,
) -> IngestPlan:
    """Ingest a codebase and produce .scope files.

    Pipeline:
    1. Build dependency graph → detect module boundaries
    2. Mine git history → change coupling, hotspots, implicit contracts
    3. Absorb existing docs → README, docstrings, signal comments
    4. Synthesize .scope files → combine all signals into scope configs
    5. Optionally write files to disk

    Args:
        root: Repository root
        mine_history: Whether to analyze git history
        absorb: Whether to absorb existing documentation
        synthesize: Whether to use LLM for context synthesis (falls back to template)
        max_commits: Max git commits to analyze
        dry_run: If True, plan but don't write files
    """
    root = os.path.abspath(root)
    plan = IngestPlan(root=root)

    # Step 1: Dependency graph
    print("Analyzing dependency graph...", file=sys.stderr)
    graph = build_graph(root)
    from .graph import format_graph_summary
    plan.graph_summary = format_graph_summary(graph)

    # Step 2: Git history
    history = HistoryAnalysis()
    if mine_history:
        print("Mining git history...", file=sys.stderr)
        history = analyze_history(root, max_commits=max_commits)
        from .history import format_history_summary
        plan.history_summary = format_history_summary(history)

    # Step 3: Doc absorption (with AST data if available)
    docs = AbsorptionResult()
    if absorb:
        print("Absorbing documentation...", file=sys.stderr)
        docs = absorb_docs(root, apis=graph.apis if graph.apis else None)

    # Step 4: Synthesize scope files
    print("Synthesizing scope files...", file=sys.stderr)
    for module in graph.modules:
        planned = _synthesize_scope(module, graph, history, docs, root, synthesize)
        if planned:
            plan.scopes.append(planned)

    # Step 5: Backtest against git history and auto-correct
    if mine_history and plan.scopes:
        print("Backtesting scopes against git history...", file=sys.stderr)
        from .backtest import backtest_scopes, auto_correct_scope, format_backtest_report

        configs = [ps.config for ps in plan.scopes]
        report = backtest_scopes(root, configs, n_commits=min(max_commits, 50))

        # Auto-correct: up to 2 rounds
        for correction_round in range(2):
            any_corrected = False
            for i, result in enumerate(report.results):
                if result.recall < 1.0 and result.missing_includes:
                    updated, changed = auto_correct_scope(
                        plan.scopes[i].config, result, root
                    )
                    if changed:
                        plan.scopes[i].config = updated
                        plan.scopes[i].signals.append(
                            f"backtest: auto-corrected {len(result.missing_includes)} missing include(s)"
                        )
                        any_corrected = True

            if not any_corrected:
                break

            # Re-run backtest after corrections
            configs = [ps.config for ps in plan.scopes]
            report = backtest_scopes(root, configs, n_commits=min(max_commits, 50))

        plan.backtest_summary = format_backtest_report(report)

    # Build .scopes index
    plan.index = _build_index(plan.scopes)

    # Step 6: Write to disk
    if not dry_run:
        _write_scopes(plan)

    return plan


def _synthesize_scope(
    module: ModuleBoundary,
    graph: DependencyGraph,
    history: HistoryAnalysis,
    docs: AbsorptionResult,
    root: str,
    use_llm: bool,
) -> Optional[PlannedScope]:
    """Synthesize a single .scope file from all available signals."""
    directory = module.directory
    scope_path = os.path.join(root, directory, ".scope")

    # Skip if .scope already exists
    if os.path.exists(scope_path):
        return None

    signals = []

    # --- Description ---
    file_count = len(module.files)
    # Detect primary language
    langs = {}
    for f in module.files:
        ext = os.path.splitext(f)[1]
        langs[ext] = langs.get(ext, 0) + 1
    primary_ext = max(langs, key=langs.get) if langs else ""
    lang_names = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
    }
    lang = lang_names.get(primary_ext, "")

    description = f"{directory} module"
    if lang:
        description = f"{directory} — {lang} module ({file_count} files)"

    signals.append(f"graph: {file_count} files, cohesion {module.cohesion:.0%}")

    # --- Includes ---
    includes = [f"{directory}/"]

    # Add cross-module dependencies detected from imports
    for dep in module.external_deps:
        dep_dir = os.path.join(root, dep)
        if os.path.isdir(dep_dir):
            # Find specific files imported, not the whole directory
            imported_files = _find_cross_module_imports(module, dep, graph)
            for imp_file in imported_files:
                if imp_file not in includes:
                    includes.append(imp_file)

    # Add change-coupled files from other modules
    for coupling in history.change_couplings:
        for f in [coupling.file_a, coupling.file_b]:
            if f.startswith(directory + "/"):
                other = coupling.file_b if f == coupling.file_a else coupling.file_a
                if not other.startswith(directory + "/") and coupling.coupling_strength >= 0.7:
                    if other not in includes:
                        includes.append(other)
                        signals.append(f"history: {other} coupled at {coupling.coupling_strength:.0%}")

    # --- Excludes ---
    excludes = _default_excludes(directory, module.files)

    # --- Context ---
    context_parts = []

    # From absorbed docs
    doc_context = docs.synthesize_context(directory, max_chars=1500)
    if doc_context:
        context_parts.append(doc_context)
        signals.append(f"docs: absorbed {len(docs.for_module(directory))} fragments")

    # From implicit contracts
    relevant_contracts = [
        ic for ic in history.implicit_contracts
        if ic.trigger_file.startswith(directory + "/")
        or ic.coupled_file.startswith(directory + "/")
    ]
    if relevant_contracts:
        context_parts.append("## Implicit Contracts (from git history)")
        for ic in relevant_contracts[:5]:
            context_parts.append(f"- {ic.description}")
        signals.append(f"history: {len(relevant_contracts)} implicit contracts")

    # From recent changes
    recent = history.recent_summaries.get(directory, [])
    if recent:
        context_parts.append("## Recent Changes")
        for msg in recent[:5]:
            context_parts.append(f"- {msg}")

    # Dependency context
    if module.external_deps:
        context_parts.append("## Dependencies")
        context_parts.append(f"This module imports from: {', '.join(module.external_deps)}")
    if module.depended_on_by:
        context_parts.append(f"This module is used by: {', '.join(module.depended_on_by)}")
        context_parts.append("Changes here may affect downstream consumers.")

    # Stability per file (from weighted history)
    stability_lines = []
    for f in module.files:
        fh = history.file_histories.get(f)
        if fh and fh.stability and fh.commit_count >= 3:
            lines_info = f", {fh.total_lines_changed} lines" if fh.total_lines_changed else ""
            stability_lines.append(
                f"- {os.path.basename(f)}: {fh.stability} ({fh.commit_count} commits{lines_info})"
            )
    if stability_lines:
        context_parts.append("## Stability")
        context_parts.extend(stability_lines[:10])

    # Transitive dependency chain (if deeper than 1 hop)
    from .graph import transitive_deps as _transitive_deps
    deep_deps = set()
    for f in module.files:
        for dep in _transitive_deps(graph, f):
            dep_parts = dep.split("/")
            if len(dep_parts) > 1 and dep_parts[0] != directory:
                deep_deps.add(dep)
    if deep_deps:
        direct = set()
        for dep in module.external_deps:
            direct.update(
                d for d in deep_deps if d.startswith(dep + "/")
            )
        transitive_only = deep_deps - direct
        if transitive_only:
            context_parts.append("## Transitive Dependencies")
            for dep in sorted(transitive_only)[:5]:
                context_parts.append(f"- {dep} (indirect)")

    # If no context was gathered, add a TODO
    if not context_parts:
        context_parts.append(
            "# TODO: Add architectural context here.\n"
            "# What invariants does this module maintain?\n"
            "# What gotchas should an agent know about?"
        )

    context_str = "\n".join(context_parts)
    context = parse_context(context_str)

    # --- Related ---
    related = []
    for dep in module.external_deps:
        scope_candidate = f"{dep}/.scope"
        related.append(scope_candidate)
    for dep_by in module.depended_on_by:
        scope_candidate = f"{dep_by}/.scope"
        if scope_candidate not in related:
            related.append(scope_candidate)

    # --- Tags ---
    tags = [directory.lower()]
    if module.external_deps:
        tags.extend(d.lower() for d in module.external_deps[:3])

    # --- Token estimate ---
    full_paths = [os.path.join(root, f) for f in module.files]
    token_est = estimate_scope_tokens(full_paths)

    # --- Confidence ---
    confidence = module.cohesion
    if doc_context:
        confidence = min(confidence + 0.1, 1.0)
    if relevant_contracts:
        confidence = min(confidence + 0.1, 1.0)

    config = ScopeConfig(
        path=scope_path,
        description=description,
        includes=includes,
        excludes=excludes,
        context=context,
        related=related,
        owners=[],
        tags=tags,
        tokens_estimate=token_est,
    )

    return PlannedScope(
        directory=directory,
        config=config,
        confidence=confidence,
        signals=signals,
    )


def _find_cross_module_imports(
    module: ModuleBoundary, dep_module: str, graph: DependencyGraph
) -> List[str]:
    """Find specific files in dep_module that are imported by files in module."""
    imported = set()
    for f in module.files:
        node = graph.files.get(f)
        if not node:
            continue
        for imp in node.imports:
            if imp.startswith(dep_module + "/"):
                imported.add(imp)
    return sorted(imported)


def _default_excludes(directory: str, files: List[str]) -> List[str]:
    """Generate sensible excludes for a module."""
    excludes = []

    # Common patterns
    excludes.append(f"{directory}/__pycache__/")
    excludes.append("*.pyc")

    # Detect test/fixture/migration directories
    subdirs = set()
    for f in files:
        parts = f.split("/")
        if len(parts) > 2:  # directory/subdir/file
            subdirs.add(parts[1])

    for subdir in subdirs:
        subdir_lower = subdir.lower()
        if subdir_lower in ("fixtures", "fixture", "testdata", "test_data", "mocks"):
            excludes.append(f"{directory}/{subdir}/")
        if subdir_lower in ("migrations", "migrate"):
            excludes.append(f"{directory}/{subdir}/")

    return excludes


def _build_index(scopes: List[PlannedScope]) -> ScopesIndex:
    """Build a .scopes index from planned scopes."""
    entries = {}
    for ps in scopes:
        name = ps.directory
        keywords = list(ps.config.tags)
        # Add words from description
        for word in ps.config.description.split():
            word = word.lower().strip("—()-,.")
            if len(word) > 2 and word not in keywords:
                keywords.append(word)

        entries[name] = ScopeEntry(
            name=name,
            path=f"{ps.directory}/.scope",
            keywords=keywords[:15],  # Cap at 15
            description=ps.config.description,
        )

    return ScopesIndex(
        version=1,
        scopes=entries,
        defaults={"max_tokens": 8000, "include_related": False},
    )


def _write_scopes(plan: IngestPlan) -> None:
    """Write all planned .scope files and the .scopes index to disk."""
    written = 0

    for ps in plan.scopes:
        scope_path = os.path.join(plan.root, ps.directory, ".scope")
        # Don't overwrite existing
        if os.path.exists(scope_path):
            continue

        os.makedirs(os.path.dirname(scope_path), exist_ok=True)
        content = serialize_scope(ps.config)
        with open(scope_path, "w", encoding="utf-8") as f:
            f.write(content)
        written += 1

    # Write .scopes index (only if it doesn't exist)
    index_path = os.path.join(plan.root, ".scopes")
    if plan.index and not os.path.exists(index_path):
        content = _serialize_index(plan.index)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)
        written += 1

    print(f"Wrote {written} file(s)", file=sys.stderr)


def _serialize_index(index: ScopesIndex) -> str:
    """Serialize a ScopesIndex to .scopes YAML format."""
    lines = [f"version: {index.version}", "", "scopes:"]

    for name, entry in sorted(index.scopes.items()):
        lines.append(f"  {name}:")
        lines.append(f"    path: {entry.path}")
        kw_str = ", ".join(entry.keywords)
        lines.append(f"    keywords: [{kw_str}]")

    lines.append("")
    lines.append("defaults:")
    for k, v in index.defaults.items():
        if isinstance(v, bool):
            lines.append(f"  {k}: {'true' if v else 'false'}")
        else:
            lines.append(f"  {k}: {v}")

    return "\n".join(lines) + "\n"


def format_ingest_report(plan: IngestPlan) -> str:
    """Format a human-readable report of the ingest plan."""
    lines = [
        f"Ingest Report for {os.path.basename(plan.root)}/",
        "=" * 50,
        "",
    ]

    if plan.graph_summary:
        lines.append(plan.graph_summary)
        lines.append("")

    if plan.history_summary:
        lines.append(plan.history_summary)
        lines.append("")

    if plan.backtest_summary:
        lines.append(plan.backtest_summary)
        lines.append("")

    lines.append(f"Planned {len(plan.scopes)} scope file(s):")
    lines.append("")

    for ps in plan.scopes:
        conf_bar = "█" * int(ps.confidence * 10) + "░" * (10 - int(ps.confidence * 10))
        lines.append(
            f"  {ps.directory}/.scope — confidence: {conf_bar} {ps.confidence:.0%}"
        )
        lines.append(f"    {ps.config.description}")
        lines.append(f"    includes: {len(ps.config.includes)} path(s), "
                      f"~{ps.config.tokens_estimate:,} tokens")
        if ps.signals:
            for sig in ps.signals:
                lines.append(f"    signal: {sig}")
        if ps.config.related:
            lines.append(f"    related: {', '.join(ps.config.related)}")
        lines.append("")

    return "\n".join(lines)
