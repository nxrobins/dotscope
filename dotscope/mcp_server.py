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

    # Parse --root argument if provided
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default=None, help="Repository root path")
    known, _remaining = parser.parse_known_args()
    _cli_root = known.root

    mcp = FastMCP("dotscope")

    # Session-level tracker (lives across tool calls in a single MCP session)
    from .visibility import SessionTracker
    tracker = SessionTracker()
    _root = None  # Will be set below

    # Load cached data from .dotscope/ for attribution hints + session stats
    _repo_tokens = 0
    _cached_history = None
    _cached_graph_hubs = {}
    try:
        from .discovery import find_repo_root
        from .parser import parse_scopes_index
        from .storage.cache import load_cached_history, load_cached_graph_hubs
        _root = find_repo_root(_cli_root)
        if _root:
            _idx_path = os.path.join(_root, ".scopes")
            if os.path.exists(_idx_path):
                _idx = parse_scopes_index(_idx_path)
                _repo_tokens = _idx.total_repo_tokens
            _cached_history = load_cached_history(_root)
            _cached_graph_hubs = load_cached_graph_hubs(_root)
            tracker.set_repo_root(_root)
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
            from .storage.near_miss import save_session_scopes
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
        task: Optional[str] = None,
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
        import time as _time
        _resolve_start = _time.perf_counter()

        from pathlib import Path
        from .composer import compose
        from .passes.budget_allocator import apply_budget
        from .discovery import find_repo_root
        from .formatter import format_resolved
        from .refresh import ensure_resolution_freshness, refresh_status_summary

        root = find_repo_root()
        dot_dir = Path(root) / ".dotscope" if root else None
        freshness = ensure_resolution_freshness(root, scope) if root else {
            "state": "fresh",
            "source": "tracked_snapshot",
            "last_refreshed": "",
            "healed": False,
            "job_kind": None,
        }
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

        # Load assertions for budget enforcement
        required_files = None
        assertions = []
        try:
            from .assertions import load_assertions, get_required_files
            module = scope.split("+")[0].split("-")[0].split("&")[0].split("@")[0]
            assertions = load_assertions(root, module)
            required_files = get_required_files(assertions, module) or None
        except Exception:
            pass

        if budget is not None:
            try:
                resolved = apply_budget(resolved, budget, utility_scores=utility_scores,
                                        required_files=required_files)
            except Exception as exc:
                # ContextExhaustionError — return as structured error
                if hasattr(exc, "to_dict"):
                    return json.dumps(exc.to_dict(), indent=2)
                raise

        # Track session (MCP calls only — compose stays pure)
        session_id = None
        try:
            from .storage.session_manager import SessionManager
            mgr = SessionManager(root)
            mgr.ensure_initialized()
            task_str = f"resolve {scope}" + (f" (budget={budget})" if budget else "")
            session_id = mgr.create_session(scope, task_str, resolved.files, resolved.context)
            resolved.context = f"# dotscope-session: {session_id}\n{resolved.context}"
            # Onboarding
            from .storage.onboarding import mark_milestone, increment_counter
            mark_milestone(root, "first_session")
            increment_counter(root, "sessions_completed")
        except Exception:
            pass  # Session tracking failures never block resolution

        # Record timing
        try:
            import time as _time
            _resolve_end = _time.perf_counter()
        except Exception:
            pass

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
                data["freshness"] = freshness

                # Constraints (prophylactic enforcement)
                try:
                    from .passes.sentinel.constraints import build_constraints
                    from .intent import load_conventions, load_intents
                    invariants = {}
                    inv_path = os.path.join(root, ".dotscope", "invariants.json")
                    if os.path.exists(inv_path):
                        with open(inv_path, "r", encoding="utf-8") as _f:
                            invariants = json.loads(_f.read())
                    scopes_data = {}
                    from .passes.sentinel.checker import _load_scopes_with_antipatterns
                    scopes_data = _load_scopes_with_antipatterns(root)
                    intents = load_intents(root)
                    conventions = load_conventions(root)
                    constraints = build_constraints(
                        module, root, invariants, scopes_data, intents,
                        graph_hubs=_cached_graph_hubs, task=task,
                        conventions=conventions,
                    )
                    if constraints:
                        data["constraints"] = [
                            {
                                "category": c.category,
                                "message": c.message,
                                "file": c.file,
                                "confidence": c.confidence,
                            }
                            for c in constraints
                        ]

                    # Routing guidance: positive-frame "what to do"
                    from .passes.sentinel.constraints import build_routing_guidance
                    vc = None
                    try:
                        from .intent import load_voice_config
                        vc = load_voice_config(root)
                    except Exception:
                        pass
                    routing = build_routing_guidance(
                        module, conventions=conventions, voice_config=vc,
                        repo_root=root,
                    )
                    if routing:
                        data["routing"] = [
                            {
                                "category": r.category,
                                "message": r.message,
                                "confidence": r.confidence,
                            }
                            for r in routing
                        ]

                    # Gap 2: Adjacent scope routing
                    from .passes.sentinel.constraints import build_adjacent_routing
                    scopes_index = {}
                    try:
                        from .scanner import load_scopes_index
                        scopes_index = load_scopes_index(root)
                    except Exception:
                        pass
                    adjacent = build_adjacent_routing(
                        module, graph_hubs=_cached_graph_hubs,
                        all_scopes=scopes_index, conventions=conventions,
                    )
                    if adjacent:
                        data["routing_adjacent"] = [
                            {
                                "scope": r.metadata.get("adjacent_scope", ""),
                                "message": r.message,
                            }
                            for r in adjacent
                        ]

                except Exception:
                    pass

                # Gap 4: Last observation feedback
                try:
                    obs_path = os.path.join(root, ".dotscope", "last_observation.json")
                    if os.path.exists(obs_path):
                        with open(obs_path, "r", encoding="utf-8") as _f:
                            last_obs = json.loads(_f.read())
                        if last_obs.get("scope") == module or not last_obs.get("scope"):
                            data["last_observation"] = last_obs
                except Exception:
                    pass

                # Voice injection
                try:
                    from .intent import load_voice_config
                    vc = load_voice_config(root)
                    if vc:
                        from .passes.voice import build_voice_response
                        data["voice"] = build_voice_response(
                            vc, root, resolved.files, conventions,
                        )
                except Exception:
                    pass

                # Track for session summary (inject _repo_tokens, then strip)
                data["_repo_tokens"] = _repo_tokens
                tracker.record_resolve(module, data)
                data.pop("_repo_tokens", None)

                # Features requiring observation data
                if dot_dir and dot_dir.exists():
                    from .storage.session_manager import SessionManager
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
                    refresh_status = refresh_status_summary(root)
                    if refresh_status.get("running") and refresh_status.get("current_job") == "repo":
                        nudges = nudges or []
                        nudges.append({
                            "scope": module,
                            "issue": "repo_refresh_running",
                            "message": "A background repo refresh is rebuilding live scopes.",
                            "suggestion": "dotscope refresh status",
                        })
                    elif any(job.get("kind") == "repo" for job in refresh_status.get("queued_jobs", [])):
                        nudges = nudges or []
                        nudges.append({
                            "scope": module,
                            "issue": "repo_refresh_queued",
                            "message": "A background repo refresh is queued for live scope updates.",
                            "suggestion": "dotscope refresh status",
                        })
                    if nudges:
                        data["health_warnings"] = nudges

                    # Feature 5: Near-misses (from persistent storage)
                    try:
                        from .storage.near_miss import load_recent_near_misses
                        nms = load_recent_near_misses(root, module)
                        if nms:
                            data["near_misses"] = nms
                    except Exception:
                        pass

                # Output assertions (ensure_context_contains, ensure_constraints)
                if assertions:
                    try:
                        from .assertions import check_output_assertions
                        module = scope.split("+")[0].split("-")[0].split("&")[0].split("@")[0]
                        err = check_output_assertions(
                            resolved.context,
                            data.get("constraints", []),
                            assertions, module,
                        )
                        if err:
                            return json.dumps(err.to_dict(), indent=2)
                    except Exception:
                        pass

                output = json.dumps(data, indent=2)
            except Exception:
                pass  # Visibility metadata is best-effort, never blocks

        # Record timing
        try:
            elapsed_ms = (_time.perf_counter() - _resolve_start) * 1000
            from .storage.timing import record_timing
            if root:
                record_timing(root, "resolve", elapsed_ms)
        except Exception:
            pass

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
        from .discovery import load_resolution_index, load_resolution_scopes
        from .matcher import match_task

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        index = load_resolution_index(root)

        scopes = []
        if index:
            for name, entry in index.scopes.items():
                scopes.append((name, entry.keywords, entry.description or ""))
        else:
            for logical_path, config, _source in load_resolution_scopes(root):
                scopes.append((os.path.dirname(logical_path) or ".", config.tags, config.description))

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
        from .discovery import find_repo_root, find_resolution_scope
        from .context import query_context
        from .refresh import ensure_resolution_freshness

        root = find_repo_root()
        if root is not None:
            ensure_resolution_freshness(root, scope)
        config = find_resolution_scope(scope, root)
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
        from .discovery import (
            find_repo_root,
            load_resolution_index,
            load_resolution_scopes,
        )

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        scopes = []
        index = load_resolution_index(root)

        if index:
            for name, entry in index.scopes.items():
                scopes.append({
                    "name": name,
                    "path": entry.path,
                    "keywords": entry.keywords,
                    "description": entry.description,
                })
        else:
            for logical_path, config, source in load_resolution_scopes(root):
                scopes.append({
                    "name": os.path.dirname(logical_path) or ".",
                    "path": logical_path,
                    "tags": config.tags,
                    "description": config.description,
                    "tokens_estimate": config.tokens_estimate,
                    "source": source,
                })

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

        report = full_health_report(root, use_runtime=True)
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
            quiet=True,
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
        from .passes.graph_builder import build_graph
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
        from .passes.backtest import backtest_scopes as _backtest
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
        from .storage.session_manager import SessionManager
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
        from .storage.session_manager import SessionManager
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
        from .storage.session_manager import SessionManager
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

    @mcp.tool()
    def dotscope_check(
        diff: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Check proposed changes against codebase rules and architectural intent.

        Call before committing. Returns holds (must address), notes (informational),
        and proposed fixes for each hold.

        If no diff provided, checks current git staged changes.
        If session_id provided, uses that session for boundary checking.
        """
        from .passes.sentinel.checker import check_diff, check_staged
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        if diff:
            report = check_diff(diff, root, session_id=session_id)
        else:
            report = check_staged(root, session_id=session_id)

        def _fmt_result(r):
            d = {
                "category": r.category.value,
                "severity": r.severity.value,
                "message": r.message,
                "file": r.file,
            }
            if r.suggestion:
                d["suggestion"] = r.suggestion
            if r.acknowledge_id:
                d["acknowledge_id"] = r.acknowledge_id
            if r.proposed_fix:
                d["proposed_fix"] = {
                    "file": r.proposed_fix.file,
                    "reason": r.proposed_fix.reason,
                    "predicted_sections": r.proposed_fix.predicted_sections,
                    "proposed_diff": r.proposed_fix.proposed_diff,
                    "confidence": r.proposed_fix.confidence,
                }
            return d

        return json.dumps({
            "passed": report.passed,
            "guards": [_fmt_result(r) for r in report.guards],
            "nudges": [_fmt_result(r) for r in report.nudges],
            "notes": [
                {
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "message": r.message,
                    "file": r.file,
                }
                for r in report.notes
            ],
            "holds": [_fmt_result(r) for r in report.guards],  # backwards compat
            "files_checked": report.files_checked,
        }, indent=2)

    @mcp.tool()
    def dotscope_debug(
        session_id: Optional[str] = None,
    ) -> str:
        """Debug why an agent session produced a bad outcome.

        Bisects the context, files, and constraints that were served
        to identify the root cause. Returns diagnosis and recommendations.

        If no session_id, debugs the most recent session with low recall.
        """
        from .debug import debug_session, list_bad_sessions
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        if not session_id:
            bad = list_bad_sessions(root, limit=1)
            if bad:
                session_id = bad[0]["session_id"]
            else:
                return json.dumps({"error": "No sessions with low recall found"})

        result = debug_session(session_id, root)
        if result is None:
            return json.dumps({"error": f"Session {session_id} not found or recall >= 80%"})

        return json.dumps({
            "session_id": result.session_id,
            "diagnosis": result.diagnosis,
            "files_that_mattered": result.files_that_mattered,
            "files_that_didnt_help": result.files_that_didnt_help,
            "missing_files": result.missing_files,
            "constraints_violated": result.constraints_violated,
            "recommendations": result.recommendations,
        }, indent=2)

    @mcp.tool()
    def dotscope_acknowledge(
        ids: str,
        reason: str,
    ) -> str:
        """Acknowledge a hold and proceed.

        Records the acknowledgment. Repeated acknowledgments of the same
        constraint cause its confidence to decay over time.

        Args:
            ids: Comma-separated acknowledge IDs from dotscope_check holds
            reason: Why this acknowledgment is correct
        """
        from .passes.sentinel.acknowledge import record_acknowledgment
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        ack_ids = [i.strip() for i in ids.split(",") if i.strip()]
        recorded = []
        for ack_id in ack_ids:
            entry = record_acknowledgment(root, ack_id, reason)
            recorded.append(entry)

        return json.dumps({
            "acknowledged": len(recorded),
            "ids": ack_ids,
            "reason": reason,
        }, indent=2)

    @mcp.tool()
    def match_conventions_by_path(
        filepath: str,
    ) -> str:
        """What conventions apply to a file path?

        Takes a file path (can be a file that doesn't exist yet) and returns
        matching conventions with their rules. Use this before creating a new
        file to understand what patterns it should follow.

        Args:
            filepath: Path to check (relative to repo root)
        """
        from .discovery import find_repo_root
        from .intent import load_conventions

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        conventions = load_conventions(root)
        if not conventions:
            return json.dumps({"matches": [], "message": "No conventions defined"})

        from .passes.sentinel.constraints import match_conventions_by_path as _match
        matches = _match(filepath, conventions)

        if not matches:
            return json.dumps({
                "matches": [],
                "message": f"No conventions match {filepath}",
            })

        return json.dumps({"matches": matches}, indent=2)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
