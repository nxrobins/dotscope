def register_ingest_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _root = kwargs.get('_root')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')
    _cli_root = kwargs.get('_cli_root')

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
    def merge_scout_findings(
        scout_reports: list,
    ) -> dict:
        """Cross-reference scout findings against codebase physics.

        Takes raw scout reports (flagged files + notes) and returns
        structurally validated connections, convergence points,
        and a unified blast radius.

        Each scout report should contain:
          scout_id: int
          flagged_files: List[str]
          notes: str (natural language findings)
          confidence: float (0-1, scout's self-assessed confidence)
        """
        from .swarm.merge import merge_scout_findings as _merge
        root = _root or _find_root()
        graph = _get_graph(root)
        invariants = _load_invariants(root)
        return _merge(scout_reports, root, graph, invariants)

