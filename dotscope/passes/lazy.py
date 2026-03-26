"""Lazy ingest: generate a single scope on demand when resolve can't find one.

When an agent (or CLI) resolves a module that hasn't been ingested yet,
this module builds a minimal scope from a partial graph and filtered history.
Full ingest fills in transitive dependencies and cross-module contracts later.
"""

import os
import sys
from pathlib import Path
from typing import Optional

from ..absorber import absorb_docs
from ..context import parse_context
from ..history import HistoryAnalysis, analyze_history
from ..models.core import ScopeConfig
from ..models.passes import PlannedScope
from ..parser import serialize_scope
from ..progress import ProgressEmitter
from ..tokens import estimate_scope_tokens


def lazy_ingest_module(
    root: str,
    module_name: str,
    quiet: bool = True,
) -> Optional[ScopeConfig]:
    """Ingest a single module on demand.

    Returns the ScopeConfig if successful, None if module dir doesn't exist.
    """
    module_name = module_name.rstrip("/")
    module_path = os.path.join(root, module_name)
    if not os.path.isdir(module_path):
        return None

    progress = ProgressEmitter(quiet=quiet)

    # Collect module files
    from .graph_builder import _collect_source_files, build_partial_graph
    all_files = _collect_source_files(root)
    module_files = [
        (rel, lang) for rel, lang in all_files
        if rel.startswith(module_name + "/") or rel.startswith(module_name + os.sep)
    ]
    if not module_files:
        return None

    # Partial graph: module files + one level of imports
    progress.start(f"lazy ingest {module_name}/ (graph)")
    graph = build_partial_graph(root, module_files)
    progress.finish(f"{len(graph.files)} files")

    # Filtered history: recent commits touching this module
    progress.start(f"lazy ingest {module_name}/ (history)")
    history = HistoryAnalysis()
    try:
        history = analyze_history(
            root, max_commits=50, paths=[module_name + "/"],
        )
    except Exception:
        pass
    progress.finish(f"{history.commits_analyzed} commits")

    # Synthesize one scope
    scope_path = os.path.join(root, module_name, ".scope")
    includes = [module_name + "/"]

    # Add cross-module imports from the partial graph
    for path, node in graph.files.items():
        if path.startswith(module_name + "/"):
            for imp in node.imports:
                if not imp.startswith(module_name + "/") and imp not in includes:
                    includes.append(imp)

    # Context from history
    context_parts = []
    if history.implicit_contracts:
        context_parts.append("## Implicit Contracts (from git history)")
        for ic in history.implicit_contracts[:5]:
            context_parts.append(f"- {ic.description}")

    # Stability
    stability_lines = []
    for rel, _ in module_files:
        fh = history.file_histories.get(rel)
        if fh and fh.stability and fh.commit_count >= 3:
            stability_lines.append(
                f"- {os.path.basename(rel)}: {fh.stability} ({fh.commit_count} commits)"
            )
    if stability_lines:
        context_parts.append("## Stability")
        context_parts.extend(stability_lines[:10])

    if not context_parts:
        context_parts.append(
            f"{module_name} module — {len(module_files)} files."
        )

    context = parse_context("\n".join(context_parts))

    # Tags
    tags = [module_name.lower()]

    # Token estimate
    full_paths = [os.path.join(root, rel) for rel, _ in module_files]
    token_est = estimate_scope_tokens(full_paths)

    config = ScopeConfig(
        path=scope_path,
        description=f"{module_name} module ({len(module_files)} files)",
        includes=includes,
        excludes=[f"{module_name}/__pycache__/", "*.pyc"],
        context=context,
        related=[],
        owners=[],
        tags=tags,
        tokens_estimate=token_est,
    )

    # Write scope file
    os.makedirs(os.path.dirname(scope_path), exist_ok=True)
    content = serialize_scope(config)
    with open(scope_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Update .scopes index
    from ..ingest import append_to_index
    planned = PlannedScope(
        directory=module_name,
        config=config,
        confidence=0.5,
        signals=["lazy: on-demand ingest"],
    )
    try:
        append_to_index(root, planned)
    except Exception:
        pass  # Index update is best-effort

    # Mark that a full re-ingest is needed
    dot_dir = os.path.join(root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)
    marker = os.path.join(dot_dir, "needs_full_ingest")
    Path(marker).touch()

    if not quiet:
        print(
            f"dotscope: {module_name}/ scoped on demand",
            file=sys.stderr,
        )

    return config
