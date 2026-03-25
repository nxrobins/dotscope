"""MCP server for dotscope — the primary agent-facing interface.

Exposes scope resolution, matching, and context as MCP tools
that any MCP-compatible agent can call.

Install: pip install dotscope[mcp]
Run: dotscope-mcp (stdio transport)

Configure in Claude Desktop or similar:
{
    "mcpServers": {
        "dotscope": {
            "command": "dotscope-mcp"
        }
    }
}
"""


import json
import os
import sys
from typing import Optional


def main():
    """MCP server entry point."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP server requires the 'mcp' package.\n"
            "Install with: pip install dotscope[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp = FastMCP(
        "dotscope",
        description=(
            "Directory-scoped context boundaries for AI coding agents. "
            "Resolve .scope files to curated file lists with architectural context."
        ),
    )

    # Session-level tracker (lives across tool calls in a single MCP session)
    from .visibility import SessionTracker
    tracker = SessionTracker()

    # Load cached data from .dotscope/ for attribution hints + session stats
    _repo_tokens = 0
    _cached_history = None
    _cached_graph_hubs = {}
    try:
        from .discovery import find_repo_root
        from .parser import parse_scopes_index
        from .cache import load_cached_history, load_cached_graph_hubs
        _root = find_repo_root()
        if _root:
            _idx_path = os.path.join(_root, ".scopes")
            if os.path.exists(_idx_path):
                _idx = parse_scopes_index(_idx_path)
                _repo_tokens = _idx.total_repo_tokens
            _cached_history = load_cached_history(_root)
            _cached_graph_hubs = load_cached_graph_hubs(_root)
    except Exception:
        pass

    # Print session summary on server shutdown
    import atexit

    def _print_session_summary():
        summary = tracker.format_terminal()
        if summary:
            print(summary, file=sys.stderr)

    def _save_session_scopes():
        try:
            from .near_miss import save_session_scopes
            scopes = list(tracker._stats.unique_scopes)
            if scopes and _root:
                save_session_scopes(_root, scopes)
        except Exception:
            pass

    atexit.register(_print_session_summary)
    atexit.register(_save_session_scopes)

    @mcp.tool()
    def resolve_scope(
        scope: str,
        budget: Optional[int] = None,
        follow_related: bool = True,
        format: str = "json",
    ) -> str:
        """Resolve a scope expression to a file list with architectural context.

        Scope expressions support composition:
        - "auth" — single scope
        - "auth+payments" — merge two scopes (union of files)
        - "auth-tests" — subtract (auth files minus test scope files)
        - "auth&api" — intersect (only files in both)
        - "auth@context" — context only, no files

        If budget is set, returns the most relevant files fitting within
        that token count. Context is always included first, then files are
        ranked by historical utility and loaded until the budget is exhausted.

        Response includes scope_accuracy when observation data exists.

        Args:
            scope: Scope name, path, or composition expression
            budget: Max tokens for context + files (None = no limit)
            follow_related: Whether to follow related scope references
            format: Output format — "json", "plain", or "cursor"
        """
        from pathlib import Path
        from .composer import compose
        from .budget import apply_budget
        from .discovery import find_repo_root
        from .formatter import format_resolved

        root = find_repo_root()
        dot_dir = Path(root) / ".dotscope" if root else None
        resolved = compose(scope, root=root, follow_related=follow_related)

        # Wire 1: inject lessons and invariants into context
        if dot_dir and dot_dir.exists():
            try:
                from .lessons import load_lessons, load_invariants, format_lessons_for_context
                module = scope.split("+")[0].split("-")[0].split("&")[0].split("@")[0]
                lessons = load_lessons(dot_dir, module)
                invariants = load_invariants(dot_dir, module)
                enrichment = format_lessons_for_context(lessons, invariants)
                if enrichment:
                    resolved.context = resolved.context + "\n\n" + enrichment
            except Exception:
                pass  # Enrichment failures never block resolution

        # Wire 3: load utility scores for budget ranking
        utility_scores = None
        if dot_dir and dot_dir.exists():
            try:
                from .utility import load_utility_scores
                utility_scores = load_utility_scores(dot_dir)
            except Exception:
                pass

        if budget is not None:
            resolved = apply_budget(resolved, budget, utility_scores=utility_scores)

        # Track session (MCP calls only — compose stays pure)
        session_id = None
        try:
            from .sessions import SessionManager
            mgr = SessionManager(root)
            mgr.ensure_initialized()
            task_str = f"resolve {scope}" + (f" (budget={budget})" if budget else "")
            session_id = mgr.create_session(scope, task_str, resolved.files, resolved.context)
            resolved.context = f"# dotscope-session: {session_id}\n{resolved.context}"
        except Exception:
            pass  # Session tracking failures never block resolution

        output = format_resolved(resolved, fmt=format, root=root)

        # Enrich JSON responses with visibility metadata
        if format == "json":
            try:
                data = json.loads(output)

                # Feature 2: Attribution hints (with provenance)
                from .visibility import (
                    extract_attribution_hints, build_accuracy,
                    check_health_nudges,
                )
                module = scope.split("+")[0].split("-")[0].split("&")[0].split("@")[0]
                contracts = (
                    _cached_history.implicit_contracts
                    if _cached_history else None
                )
                data["attribution_hints"] = extract_attribution_hints(
                    resolved.context,
                    implicit_contracts=contracts,
                    graph_hubs=_cached_graph_hubs,
                    scope_directory=module,
                )

                # Track for session summary (inject _repo_tokens, then strip)
                data["_repo_tokens"] = _repo_tokens
                tracker.record_resolve(module, data)
                data.pop("_repo_tokens", None)

                # Features requiring observation data
                if dot_dir and dot_dir.exists():
                    from .sessions import SessionManager
                    mgr = SessionManager(root)
                    sessions = mgr.get_sessions(limit=200)
                    scope_session_ids = {
                        s.session_id for s in sessions
                        if scope in s.scope_expr
                    }
                    observations = [
                        o for o in mgr.get_observations(limit=200)
                        if o.session_id in scope_session_ids
                    ]

                    # Unified accuracy (merges scope_accuracy + recent_learning)
                    accuracy = build_accuracy(observations, scope)
                    if accuracy:
                        data["accuracy"] = accuracy

                    # Feature 4: Health nudges
                    nudges = check_health_nudges(
                        observations, scope, repo_root=root,
                    )
                    if nudges:
                        data["health_warnings"] = nudges

                    # Feature 5: Near-misses (from persistent storage)
                    try:
                        from .near_miss import load_recent_near_misses
                        nms = load_recent_near_misses(root, module)
                        if nms:
                            data["near_misses"] = nms
                    except Exception:
                        pass

                output = json.dumps(data, indent=2)
            except Exception:
                pass  # Visibility metadata is best-effort, never blocks

        return output

    @mcp.tool()
    def match_scope(task: str) -> str:
        """Find the most relevant scope(s) for a task description.

        Uses keyword overlap between the task and scope keywords/tags/descriptions.
        Returns a ranked list with confidence scores.

        Args:
            task: Natural language description of what you're working on
        """
        from .discovery import find_repo_root, load_index, find_all_scopes
        from .matcher import match_task
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        index = load_index(root)
        scope_files = find_all_scopes(root)

        scopes = []
        if index:
            for name, entry in index.scopes.items():
                scopes.append((name, entry.keywords, entry.description or ""))
        else:
            for sf in scope_files:
                try:
                    config = parse_scope_file(sf)
                    name = os.path.relpath(os.path.dirname(sf), root)
                    scopes.append((name, config.tags, config.description))
                except (ValueError, IOError):
                    continue

        matches = match_task(task, scopes)

        return json.dumps({
            "matches": [
                {"scope": name, "confidence": round(score, 3)}
                for name, score in matches
            ],
            "task": task,
        }, indent=2)

    @mcp.tool()
    def get_context(scope: str, section: Optional[str] = None) -> str:
        """Get architectural context for a scope without loading any files.

        This is the knowledge that isn't in the code itself: invariants,
        gotchas, conventions, architectural decisions.

        Args:
            scope: Scope name or path
            section: Optional section name to filter (e.g., "invariants", "gotchas")
        """
        from .discovery import find_scope, find_repo_root
        from .context import query_context

        root = find_repo_root()
        config = find_scope(scope, root)
        if config is None:
            return json.dumps({"error": f"Scope not found: {scope}"})

        result = query_context(config.context, section)
        return json.dumps({
            "scope": scope,
            "section": section,
            "context": result,
            "description": config.description,
        }, indent=2)

    @mcp.tool()
    def list_scopes() -> str:
        """List all available scopes with descriptions, tags, and token estimates.

        Searches the .scopes index and/or walks the directory tree for .scope files.
        """
        from .discovery import find_repo_root, load_index, find_all_scopes
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        scopes = []
        index = load_index(root)

        if index:
            for name, entry in index.scopes.items():
                scopes.append({
                    "name": name,
                    "path": entry.path,
                    "keywords": entry.keywords,
                    "description": entry.description,
                })
        else:
            for sf in find_all_scopes(root):
                try:
                    config = parse_scope_file(sf)
                    scopes.append({
                        "name": os.path.relpath(os.path.dirname(sf), root),
                        "path": os.path.relpath(sf, root),
                        "tags": config.tags,
                        "description": config.description,
                        "tokens_estimate": config.tokens_estimate,
                    })
                except (ValueError, IOError):
                    continue

        return json.dumps({"scopes": scopes, "count": len(scopes)}, indent=2)

    @mcp.tool()
    def validate_scopes() -> str:
        """Validate all .scope files for broken paths and common issues.

        Checks:
        - Include paths exist
        - Related scope files exist
        - Description is not empty
        - Context field is present (the most valuable part)
        """
        from .discovery import find_repo_root, find_all_scopes
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        issues = []
        for sf in find_all_scopes(root):
            rel = os.path.relpath(sf, root)
            try:
                config = parse_scope_file(sf)
            except ValueError as e:
                issues.append({"scope": rel, "severity": "error", "message": str(e)})
                continue

            for inc in config.includes:
                full = os.path.normpath(os.path.join(root, inc))
                if not os.path.exists(full.rstrip("/")):
                    issues.append({
                        "scope": rel, "severity": "error",
                        "message": f"include path not found: {inc}",
                    })

            if not config.context_str.strip():
                issues.append({
                    "scope": rel, "severity": "warning",
                    "message": "no context — this is the most valuable part",
                })

        return json.dumps({"issues": issues, "count": len(issues)}, indent=2)

    @mcp.tool()
    def scope_health() -> str:
        """Report on scope health: staleness, coverage gaps, and import drift.

        Staleness: files changed since .scope was last modified
        Coverage: directories with no .scope file
        Drift: imports in scoped files that aren't in the includes list
        """
        from .health import full_health_report
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        report = full_health_report(root)
        return json.dumps({
            "scopes_checked": report.scopes_checked,
            "coverage_pct": round(report.coverage_pct, 1),
            "directories_covered": report.directories_covered,
            "directories_total": report.directories_total,
            "issues": [
                {
                    "scope": i.scope_path,
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                }
                for i in report.issues
            ],
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
        }, indent=2)

    @mcp.tool()
    def ingest_codebase(
        directory: str = ".",
        mine_history: bool = True,
        absorb_docs: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Reverse-engineer .scope files from an existing codebase.

        Analyzes the dependency graph, mines git history, and absorbs existing
        documentation to produce complete .scope files for every detected module.

        This is how dotscope enters any codebase — no manual .scope writing needed.

        Args:
            directory: Repository root to ingest (default: current directory)
            mine_history: Whether to analyze git history for change patterns
            absorb_docs: Whether to scan for README, docstrings, signal comments
            dry_run: If True, return the plan without writing files
        """
        from .ingest import ingest

        root = os.path.abspath(directory)
        plan = ingest(
            root,
            mine_history=mine_history,
            absorb=absorb_docs,
            dry_run=dry_run,
        )

        # Discovery data for programmatic consumers
        from .ingest import (
            _is_cross_module, _find_hub_discoveries, _find_volatility_surprises,
        )
        cross_module_contracts = []
        if plan.history and plan.history.implicit_contracts:
            cross_module_contracts = [
                ic for ic in plan.history.implicit_contracts
                if _is_cross_module(ic.trigger_file, ic.coupled_file)
                and ic.confidence >= 0.65
            ]
        hubs = _find_hub_discoveries(plan.graph) if plan.graph else []
        surprises = (
            _find_volatility_surprises(plan.history) if plan.history else []
        )

        # Token reduction
        real_scopes = [
            ps for ps in plan.scopes
            if not ps.directory.startswith("virtual/")
        ]
        token_reduction = None
        if plan.total_repo_tokens > 0 and real_scopes:
            avg = sum(
                s.config.tokens_estimate or 0 for s in real_scopes
            ) / max(len(real_scopes), 1)
            token_reduction = round(
                (1 - avg / plan.total_repo_tokens) * 100, 1
            )

        return json.dumps({
            "scopes_planned": len(plan.scopes),
            "scopes": [
                {
                    "directory": ps.directory,
                    "description": ps.config.description,
                    "confidence": round(ps.confidence, 3),
                    "includes_count": len(ps.config.includes),
                    "token_estimate": ps.config.tokens_estimate,
                    "signals": ps.signals,
                    "has_context": bool(ps.config.context_str.strip()),
                }
                for ps in plan.scopes
            ],
            "dry_run": dry_run,
            "graph_summary": plan.graph_summary,
            "total_repo_files": plan.total_repo_files,
            "total_repo_tokens": plan.total_repo_tokens,
            "token_reduction_pct": token_reduction,
            "discoveries": {
                "implicit_contracts": len(cross_module_contracts),
                "cross_cutting_hubs": len(hubs),
                "volatility_surprises": len(surprises),
            },
        }, indent=2)

    @mcp.tool()
    def impact_analysis(file_path: str) -> str:
        """Predict the blast radius of changes to a specific file.

        Returns which files import this file (direct dependents),
        transitive dependents, and which scopes are affected.

        Args:
            file_path: Path to the file to analyze (relative to repo root)
        """
        from .graph import build_graph
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        graph = build_graph(root)
        target = os.path.relpath(os.path.abspath(file_path), root)
        node = graph.files.get(target)

        if not node:
            return json.dumps({"error": f"File not found in graph: {target}"})

        # Transitive dependents
        transitive = set()
        for direct in node.imported_by:
            dep_node = graph.files.get(direct)
            if dep_node:
                for t in dep_node.imported_by:
                    if t != target:
                        transitive.add(t)

        affected_modules = set()
        for f in list(node.imported_by) + list(transitive):
            parts = f.split("/")
            if len(parts) > 1:
                affected_modules.add(parts[0])

        total = 1 + len(node.imported_by) + len(transitive)
        risk = "low" if total <= 3 else ("medium" if total <= 10 else "high")

        return json.dumps({
            "file": target,
            "imports": node.imports,
            "imported_by": node.imported_by,
            "transitive_dependents": sorted(transitive),
            "affected_modules": sorted(affected_modules),
            "blast_radius": total,
            "risk": risk,
        }, indent=2)

    @mcp.tool()
    def backtest_scopes_tool(commits: int = 50) -> str:
        """Validate existing scopes against git history.

        Replays recent commits and measures whether each scope's includes
        would have covered the files actually changed. Reports recall
        per scope and suggests missing includes.

        Args:
            commits: Number of recent commits to test against
        """
        from .backtest import backtest_scopes as _backtest
        from .discovery import find_repo_root, find_all_scopes
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        configs = []
        for sf in find_all_scopes(root):
            try:
                configs.append(parse_scope_file(sf))
            except (ValueError, IOError):
                continue

        if not configs:
            return json.dumps({"error": "No .scope files found"})

        report = _backtest(root, configs, n_commits=commits)
        return json.dumps({
            "total_commits": report.total_commits,
            "overall_recall": report.overall_recall,
            "results": [
                {
                    "scope": r.scope_path,
                    "recall": r.recall,
                    "commits_tested": r.total_commits,
                    "fully_covered": r.fully_covered,
                    "missing_includes": [
                        {"path": m.path, "appearances": m.appearances}
                        for m in r.missing_includes
                    ],
                }
                for r in report.results
            ],
        }, indent=2)

    @mcp.tool()
    def scope_observations(scope: str, limit: int = 20) -> str:
        """View observation history for a scope (recall/precision trends).

        Shows how well this scope's predictions matched actual agent behavior.

        Args:
            scope: Scope name
            limit: Max observations to return
        """
        from .sessions import SessionManager
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        mgr = SessionManager(root)
        sessions = [s for s in mgr.get_sessions(limit=200) if scope in s.scope_expr]
        session_ids = {s.session_id for s in sessions}
        observations = [
            o for o in mgr.get_observations(limit=200)
            if o.session_id in session_ids
        ][:limit]

        return json.dumps({
            "scope": scope,
            "total_sessions": len(sessions),
            "total_observations": len(observations),
            "observations": [
                {
                    "commit": o.commit_hash[:8],
                    "recall": o.recall,
                    "precision": o.precision,
                    "gaps": o.touched_not_predicted[:5],
                }
                for o in observations
            ],
        }, indent=2)

    @mcp.tool()
    def scope_lessons(scope: str) -> str:
        """Get machine-generated lessons for a scope without full resolution.

        Returns patterns learned from observation data: files consistently
        needed but missing, files included but never used, hotspots.

        Args:
            scope: Scope name
        """
        from .sessions import SessionManager
        from .lessons import generate_lessons
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        mgr = SessionManager(root)
        sessions = mgr.get_sessions(limit=200)
        observations = mgr.get_observations(limit=200)
        lessons = generate_lessons(sessions, observations, module=scope)

        return json.dumps({
            "scope": scope,
            "lessons": [
                {
                    "trigger": item.trigger,
                    "lesson": item.lesson_text,
                    "confidence": item.confidence,
                }
                for item in lessons
            ],
        }, indent=2)

    @mcp.tool()
    def suggest_scope_changes(scope: str) -> str:
        """Suggest changes to a scope based on observation data.

        Recommends includes to add (frequently needed but missing)
        and includes to deprioritize (resolved but never modified).

        Args:
            scope: Scope name
        """
        from .sessions import SessionManager
        from .utility import compute_utility_scores
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        mgr = SessionManager(root)
        sessions = mgr.get_sessions(limit=200)
        observations = mgr.get_observations(limit=200)

        if not observations:
            return json.dumps({"error": "No observations yet"})

        scores = compute_utility_scores(sessions, observations)

        add = []
        deprioritize = []

        for path, score in scores.items():
            if scope in path or any(scope in s.scope_expr for s in sessions if path in s.predicted_files):
                if score.resolve_count >= 5 and score.utility_ratio == 0:
                    deprioritize.append({"path": path, "resolved": score.resolve_count})
                if score.touch_count >= 3 and score.resolve_count == 0:
                    add.append({"path": path, "touched": score.touch_count})

        return json.dumps({
            "scope": scope,
            "suggest_add": add,
            "suggest_deprioritize": deprioritize,
        }, indent=2)

    @mcp.tool()
    def session_summary() -> str:
        """Get a summary of the current MCP session's dotscope usage.

        Call this at the end of a task to see how many scopes were resolved,
        tokens served, and reduction achieved. Helps the developer understand
        what dotscope contributed to the session.
        """
        summary = tracker.summary()
        # Also print to stderr for terminal visibility
        terminal = tracker.format_terminal()
        if terminal:
            print(terminal, file=sys.stderr)
        return json.dumps(summary, indent=2)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
