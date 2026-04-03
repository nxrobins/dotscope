def register_core_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _root = kwargs.get('_root')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')
    _cli_root = kwargs.get('_cli_root')

    @mcp.tool()
    def resolve_scope(
        scope: str,
        budget: Optional[int] = None,
        follow_related: bool = True,
        format: str = "json",
        task: Optional[str] = None,
    ) -> str:
        """Get files, context, and constraints for a known scope.

        Use when you already know which scope to work in (e.g., "billing",
        "auth"). For discovery from a task description, use codebase_search.

        Args:
            scope: Scope name or composition ("auth", "auth+payments",
                "auth-tests", "auth&api", "auth@context").
            budget: Token budget (None = no limit).
            follow_related: Include related scopes.
            format: "json", "plain", or "cursor".
            task: Task description for smarter file ranking.

        Returns JSON with:
        - files: ranked by relevance, budget-fitted. Trust the ranking.
        - context: architectural knowledge (contracts, gotchas, stability).
        - constraints: rules to follow. GUARD severity blocks your commit.
          Co-change contracts mean both files must change together.
        - action_hints: imperative directives. Read these first.

        Check constraints before writing. Co-change contracts require
        paired modifications. Run dotscope_check before committing.
        """
        import time as _time
        _resolve_start = _time.perf_counter()

        from pathlib import Path
        from .composer import compose
        from .passes.budget_allocator import apply_budget
        from .paths.repo import find_repo_root
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
        # Auto-compose from task when scope is a simple name and task is provided
        _is_simple_name = not any(c in scope for c in "+-&@")
        if task and _is_simple_name:
            from .composer import compose_for_task
            resolved = compose_for_task(task, root=root, max_scopes=3)
            if not resolved.files:
                resolved = compose(scope, root=root, follow_related=follow_related)
        else:
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
        from .paths.repo import find_repo_root
        from .discovery import load_index, find_all_scopes
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
        from .paths.repo import find_repo_root
        from .discovery import find_resolution_scope
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
