"""Ingest: reverse-engineer .scope files from an existing codebase.

Orchestrates graph analysis, git history mining, and doc absorption
to produce complete .scope files for every detected module boundary.

This is how dotscope enters any codebase — not by asking humans to write
.scope files, but by inferring them from signals already in the code.
"""


import os
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

from .absorber import AbsorptionResult, absorb_docs
from .context import parse_context
from .graph import DependencyGraph, ModuleBoundary, build_graph, transitive_dependents
from .history import HistoryAnalysis, analyze_history
from .models.core import ScopeConfig, ScopesIndex, ScopeEntry
from .models.passes import IngestPlan, PlannedScope  # noqa: F401
from .models.state import BacktestReport
from .parser import serialize_scope
from .tokens import estimate_scope_tokens


def ingest(
    root: str,
    mine_history: bool = True,
    absorb: bool = True,
    synthesize: bool = True,
    max_commits: int = 500,
    dry_run: bool = False,
    quiet: bool = False,
    voice_override: Optional[str] = None,
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

    from .progress import ProgressEmitter
    progress = ProgressEmitter(quiet=quiet)

    # Step 1: Dependency graph
    progress.start("building dependency graph")
    graph = build_graph(root)
    plan.graph = graph
    plan.total_repo_files = len(graph.files)
    plan.total_repo_tokens = sum(
        estimate_scope_tokens([os.path.join(root, p)])
        for p in graph.files
    )
    from .graph import format_graph_summary
    plan.graph_summary = format_graph_summary(graph)
    edge_count = sum(len(n.imports) for n in graph.files.values())
    progress.finish(f"{len(graph.files)} files, {edge_count} edges, {len(graph.modules)} modules")

    # Step 2: Git history
    history = HistoryAnalysis()
    if mine_history:
        progress.start(f"mining git history ({max_commits} commits)")
        history = analyze_history(root, max_commits=max_commits)
        from .history import format_history_summary
        plan.history_summary = format_history_summary(history)
        contracts = len(history.implicit_contracts)
        progress.finish(f"{history.commits_analyzed} commits, {contracts} contracts")
    else:
        progress.skip("mining git history", "disabled")
    plan.history = history

    # Step 3: Doc absorption (with AST data if available)
    docs = AbsorptionResult()
    if absorb:
        progress.start("absorbing documentation")
        docs = absorb_docs(root, apis=graph.apis if graph.apis else None)
        progress.finish(f"{len(docs.fragments)} fragments")
    else:
        progress.skip("absorbing documentation", "disabled")

    # Step 3b: Discover conventions from structural patterns
    if graph.apis:
        progress.start("discovering conventions")
        from .passes.convention_discovery import discover_conventions
        from .passes.convention_parser import parse_conventions
        from .passes.convention_compliance import compute_compliance
        discovered = discover_conventions(graph.apis, graph, history)
        if discovered:
            nodes = parse_conventions(graph.apis, discovered)
            for conv in discovered:
                conv.compliance = compute_compliance(conv, nodes, graph.apis)
            viable = [c for c in discovered if c.compliance >= 0.5]
            plan.discovered_conventions = viable
            if viable and not dry_run:
                from .intent import save_conventions
                save_conventions(root, viable)
            progress.finish(f"{len(viable) if discovered else 0} patterns")
        else:
            progress.finish("0 patterns")

    # Step 3c: Voice discovery
    if graph.apis:
        progress.start("discovering voice")
        from .passes.voice_discovery import detect_codebase_maturity, discover_voice
        from .passes.voice_defaults import prescriptive_defaults
        maturity = detect_codebase_maturity(graph.apis, history, voice_override)
        if maturity == "new":
            discovered_voice = prescriptive_defaults()
        else:
            discovered_voice = discover_voice(graph.apis, root)
        if not dry_run:
            from .intent import save_voice_config
            save_voice_config(root, discovered_voice)
        progress.finish(f"{maturity} mode")

    # Step 4: Synthesize scope files
    progress.start("generating scopes")
    for module in graph.modules:
        planned = synthesize_scope(module, graph, history, docs, root, synthesize)
        if planned:
            plan.scopes.append(planned)

    # Step 4b: Detect virtual (cross-cutting) scopes
    from .virtual import detect_virtual_scopes
    virtual_scopes = detect_virtual_scopes(graph)
    plan.virtual_scopes = virtual_scopes
    for vs in virtual_scopes:
        plan.scopes.append(PlannedScope(
            directory=f"virtual/{vs.description.split('(')[0].strip().split(':')[-1].strip()}",
            config=vs,
            confidence=0.7,
            signals=["graph: cross-cutting hub detection"],
        ))
    real_count = len([s for s in plan.scopes if not s.directory.startswith("virtual/")])
    virtual_count = len(virtual_scopes)
    progress.finish(f"{real_count} scopes, {virtual_count} virtual")

    # Step 5: Backtest against git history and auto-correct
    if mine_history and plan.scopes:
        progress.start(f"backtesting ({min(max_commits, 50)} commits)")
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
        plan.backtest_report = report
        progress.finish(f"{report.overall_recall:.0%} recall")
    elif not mine_history:
        progress.skip("backtesting", "no history")

    # Build .scopes index
    plan.index = _build_index(plan.scopes, plan.total_repo_tokens)

    # Step 6: Write to disk
    if not dry_run:
        _write_scopes(plan)
        # Cache structured data for MCP server
        from .cache import cache_ingest_data
        cache_ingest_data(root, history=plan.history, graph=plan.graph)
        # Cache invariants for enforcement
        _cache_invariants(root, plan.history)
        # Reset incremental state + remove needs_full_ingest marker
        try:
            from .storage.incremental_state import reset_incremental_state
            reset_incremental_state(root)
            marker = os.path.join(root, ".dotscope", "needs_full_ingest")
            if os.path.exists(marker):
                os.remove(marker)
        except Exception:
            pass

    return plan


def synthesize_scope(
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
        description = f"{directory} -- {lang} module ({file_count} files)"

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

    # --- Context (priority: contracts → stability → docs → deps → recent → transitive) ---
    context_parts = []

    # 1. Implicit contracts FIRST — the thing nobody documented
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

    # 2. Stability profiles — which files are fragile
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

    # 3. Absorbed docs — READMEs, docstrings, signal comments
    doc_context = docs.synthesize_context(directory, max_chars=1500)
    if doc_context:
        context_parts.append(doc_context)
        signals.append(f"docs: absorbed {len(docs.for_module(directory))} fragments")

    # 4. Dependencies + structural
    if module.external_deps:
        context_parts.append("## Dependencies")
        context_parts.append(f"This module imports from: {', '.join(module.external_deps)}")
    if module.depended_on_by:
        context_parts.append(f"This module is used by: {', '.join(module.depended_on_by)}")
        context_parts.append("Changes here may affect downstream consumers.")

    # 5. Recent changes
    recent = history.recent_summaries.get(directory, [])
    if recent:
        context_parts.append("## Recent Changes")
        for msg in recent[:5]:
            context_parts.append(f"- {msg}")

    # 6. Transitive dependency chain (if deeper than 1 hop)
    from .graph import transitive_deps as _transitive_deps
    deep_deps: Set[str] = set()
    for f in module.files:
        for dep in _transitive_deps(graph, f):
            dep_parts = dep.split("/")
            if len(dep_parts) > 1 and dep_parts[0] != directory:
                deep_deps.add(dep)
    if deep_deps:
        direct: Set[str] = set()
        for dep in module.external_deps:
            direct.update(d for d in deep_deps if d.startswith(dep + "/"))
        transitive_only = deep_deps - direct
        if transitive_only:
            context_parts.append("## Transitive Dependencies")
            for dep in sorted(transitive_only)[:5]:
                context_parts.append(f"- {dep} (indirect)")

    # 7. NEVER TODO. If empty, synthesize from graph structure.
    if not context_parts:
        context_parts.append(
            f"{directory} module -- {file_count} files, "
            f"cohesion {module.cohesion:.0%}, "
            f"{len(module.external_deps)} external dependencies."
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


def _build_index(
    scopes: List[PlannedScope], total_repo_tokens: int = 0,
) -> ScopesIndex:
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
        total_repo_tokens=total_repo_tokens,
    )


def append_to_index(root: str, planned: PlannedScope) -> None:
    """Append a single scope entry to the .scopes index on disk."""
    from .discovery import load_index
    index = load_index(root)
    if index is None:
        index = ScopesIndex(version=1, scopes={}, defaults={"max_tokens": 8000, "include_related": False})

    name = planned.directory
    keywords = list(planned.config.tags)
    for word in planned.config.description.split():
        word = word.lower().strip("—()-,.")
        if len(word) > 2 and word not in keywords:
            keywords.append(word)

    index.scopes[name] = ScopeEntry(
        name=name,
        path=f"{planned.directory}/.scope",
        keywords=keywords[:15],
        description=planned.config.description,
    )

    index_path = os.path.join(root, ".scopes")
    content = _serialize_index(index)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)


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

    pass  # Progress is handled by the caller


def _serialize_index(index: ScopesIndex) -> str:
    """Serialize a ScopesIndex to .scopes YAML format."""
    lines = [f"version: {index.version}"]
    if index.total_repo_tokens:
        lines.append(f"total_repo_tokens: {index.total_repo_tokens}")
    lines.extend(["", "scopes:"])

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


def _use_unicode() -> bool:
    """Check if stdout can handle Unicode (emoji, box-drawing)."""
    import io
    enc = getattr(sys.stdout, "encoding", None) or ""
    if isinstance(sys.stdout, io.TextIOWrapper):
        enc = sys.stdout.encoding or ""
    return enc.lower().replace("-", "") in ("utf8", "utf16", "utf32", "utf8sig")


# Glyph sets: Unicode vs ASCII-safe fallbacks
_GLYPHS_UNICODE = {
    "discoveries": "\u26a1 Discoveries",
    "validation": "\U0001f4ca Validation",
    "created": "\U0001f4c1 Created",
    "bar_full": "\u2588",
    "bar_empty": "\u2591",
    "arrow": "\u2192",
    "dash": "\u2014",
    "attention": "\u2190 needs attention",
}
_GLYPHS_ASCII = {
    "discoveries": ">> Discoveries",
    "validation": ">> Validation",
    "created": ">> Created",
    "bar_full": "#",
    "bar_empty": ".",
    "arrow": "->",
    "dash": "--",
    "attention": "<- needs attention",
}


def _glyphs() -> dict:
    """Return the appropriate glyph set for the current terminal."""
    return _GLYPHS_UNICODE if _use_unicode() else _GLYPHS_ASCII


def format_ingest_report(plan: IngestPlan) -> str:
    """Format the discovery-first ingest report."""
    g = _glyphs()
    lines = []

    # --- Header ---
    real_scopes = [s for s in plan.scopes if not s.directory.startswith("virtual/")]
    module_count = len(real_scopes)
    lines.append(
        f"dotscope scanned {plan.total_repo_files} files "
        f"across {module_count} modules."
    )
    lines.append("")

    # --- Section 1: Discoveries ---
    discoveries = _extract_discoveries(plan, g)
    if discoveries:
        lines.append(g["discoveries"])
        lines.append("")
        lines.extend(discoveries)

    # --- Section 2: Validation ---
    validation = _extract_validation(plan, g)
    if validation:
        lines.append(g["validation"])
        lines.append("")
        lines.extend(validation)

    # --- Section 3: Files created ---
    lines.append(f"{g['created']} {len(real_scopes)} .scope files + .scopes index")
    lines.append("")
    lines.append("  Try it:  dotscope resolve <module>")
    lines.append("  See it:  dotscope resolve <module> --json --budget 4000")
    lines.append("  Trust it: dotscope backtest --commits 500")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discovery extraction helpers
# ---------------------------------------------------------------------------


def _is_cross_module(file_a: str, file_b: str) -> bool:
    """True if two files are in different top-level directories."""
    dir_a = file_a.split("/")[0] if "/" in file_a else ""
    dir_b = file_b.split("/")[0] if "/" in file_b else ""
    return dir_a != dir_b and bool(dir_a) and bool(dir_b)


def _find_hub_discoveries(
    graph: DependencyGraph,
) -> List[Tuple[str, int, int, int]]:
    """Find files with high import fan-in across multiple modules.

    Returns: [(path, importer_count, directory_count, blast_radius)]
    """
    results = []
    for path, node in graph.files.items():
        if not node.imported_by:
            continue
        importer_dirs: Set[str] = set()
        for imp_by in node.imported_by:
            parts = Path(imp_by).parts
            if len(parts) > 1:
                importer_dirs.add(parts[0])

        if len(node.imported_by) >= 3 and len(importer_dirs) >= 2:
            blast = transitive_dependents(graph, path)
            results.append((
                path,
                len(node.imported_by),
                len(importer_dirs),
                len(blast) + 1,  # +1 for the file itself
            ))

    results.sort(key=lambda x: -x[1])
    return results


# Directories an engineer expects to be stable
_EXPECTED_STABLE = {
    "config", "configs", "settings", "constants",
    "migrations", "fixtures", "static",
}


def _find_volatility_surprises(
    history: HistoryAnalysis,
) -> List[Tuple[str, "FileHistory"]]:
    """Files classified volatile that live in directories expected to be stable."""
    from .history import FileHistory  # noqa: F811 — type hint only

    surprises: List[Tuple[str, FileHistory]] = []
    for path, fh in history.file_histories.items():
        if fh.stability != "volatile":
            continue
        parts = path.split("/")
        if len(parts) > 1 and parts[0].lower() in _EXPECTED_STABLE:
            surprises.append((path, fh))

    # Also include the repo's most-changed file if high churn
    if history.hotspots:
        top_path, _top_churn = history.hotspots[0]
        top_fh = history.file_histories.get(top_path)
        if top_fh and top_fh.commit_count >= 10:
            if not any(p == top_path for p, _ in surprises):
                surprises.insert(0, (top_path, top_fh))

    surprises.sort(key=lambda x: -x[1].total_lines_changed)
    return surprises


def _extract_discoveries(plan: IngestPlan, g: Optional[dict] = None) -> List[str]:
    """Extract surprising findings from history, graph, and docs."""
    if g is None:
        g = _glyphs()
    lines: List[str] = []
    history = plan.history
    graph = plan.graph

    # --- Hidden dependencies (cross-module implicit contracts) ---
    if history and history.implicit_contracts:
        cross_module = [
            ic for ic in history.implicit_contracts
            if _is_cross_module(ic.trigger_file, ic.coupled_file)
            and ic.confidence >= 0.65
        ]
        if cross_module:
            lines.append(
                f"  Hidden dependencies "
                f"(from {history.commits_analyzed} commits of git history):"
            )
            for ic in cross_module[:5]:
                trigger = os.path.basename(ic.trigger_file)
                coupled = os.path.basename(ic.coupled_file)
                if trigger == coupled:
                    trigger = ic.trigger_file
                    coupled = ic.coupled_file
                lines.append(
                    f"    {trigger} {g['arrow']} {coupled}"
                    f"    {ic.confidence:.0%} co-change, undocumented"
                )
            lines.append("")

    # --- Cross-cutting hubs (from graph analysis) ---
    if graph:
        hubs = _find_hub_discoveries(graph)
        if hubs:
            for hub_path, importer_count, dir_count, blast_radius in hubs[:3]:
                lines.append("  Cross-cutting hub:")
                lines.append(
                    f"    {hub_path} is imported by "
                    f"{importer_count} files across {dir_count} modules"
                )
                if blast_radius > importer_count:
                    lines.append(
                        f"    A change here affects "
                        f"{blast_radius} files transitively"
                    )
            lines.append("")

    # --- Volatility surprises ---
    if history and history.file_histories:
        surprises = _find_volatility_surprises(history)
        if surprises:
            lines.append("  Volatility surprise:")
            for path, fh in surprises[:3]:
                lines.append(
                    f"    {path} {g['dash']} {fh.commit_count} commits, "
                    f"{fh.total_lines_changed} lines changed"
                )
            # Annotate if top file has no scope covering it
            if surprises:
                top_path = surprises[0][0]
                has_scope = any(
                    top_path.startswith(s.directory + "/")
                    for s in plan.scopes
                )
                if not has_scope:
                    lines.append(
                        "    Most changed file in the repo. "
                        "No .scope context exists for it."
                    )
            lines.append("")

    return lines


def _extract_validation(plan: IngestPlan, g: Optional[dict] = None) -> List[str]:
    """Extract validation stats: backtest recall + token reduction."""
    if g is None:
        g = _glyphs()
    lines: List[str] = []
    report = plan.backtest_report

    if not report or report.total_commits == 0:
        return lines

    lines.append(
        f"  Backtested against {report.total_commits} recent commits:"
    )
    lines.append(
        f"  Overall recall: {report.overall_recall:.0%} {g['dash']} "
        f"scopes would have given agents the right files"
    )

    # Token reduction ratio — the single most compelling number
    real_scopes = [
        s for s in plan.scopes
        if not s.directory.startswith("virtual/")
    ]
    if plan.total_repo_tokens > 0 and real_scopes:
        avg_scope_tokens = sum(
            s.config.tokens_estimate or 0 for s in real_scopes
        ) / max(len(real_scopes), 1)
        reduction = (1 - avg_scope_tokens / plan.total_repo_tokens) * 100
        lines.append(
            f"  Token reduction: {reduction:.0f}% {g['dash']} "
            f"from ~{plan.total_repo_tokens:,} to "
            f"~{int(avg_scope_tokens):,} average per resolution"
        )

    lines.append("")

    # Per-scope recall bars
    for result in report.results:
        scope_name = os.path.basename(os.path.dirname(result.scope_path))
        if result.total_commits == 0:
            continue
        filled = int(result.recall * 10)
        bar = g["bar_full"] * filled + g["bar_empty"] * (10 - filled)
        suffix = f" {g['attention']}" if result.recall < 0.8 else ""
        lines.append(
            f"  {scope_name:<12} {bar} {result.recall:.0%} recall{suffix}"
        )

    return lines


def _cache_invariants(root: str, history: Optional[HistoryAnalysis]) -> None:
    """Cache invariants.json with contracts, function_co_changes, and file_stabilities."""
    if not history:
        return

    dot_dir = os.path.join(root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)

    contracts = []
    for ic in history.implicit_contracts:
        contracts.append({
            "trigger_file": ic.trigger_file,
            "coupled_file": ic.coupled_file,
            "confidence": ic.confidence,
            "description": ic.description,
        })

    stabilities = {}
    for path, fh in history.file_histories.items():
        stabilities[path] = {
            "classification": fh.stability,
            "commit_count": fh.commit_count,
        }

    invariants = {
        "contracts": contracts,
        "function_co_changes": {},  # Populated when function-level data available
        "file_stabilities": stabilities,
    }

    import json
    path = os.path.join(dot_dir, "invariants.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(invariants, f, indent=2)
