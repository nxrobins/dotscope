def register_hooks_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _root = kwargs.get('_root')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')
    _cli_root = kwargs.get('_cli_root')

    @mcp.tool()
    def dotscope_sync(
        scopes: list[str] | None = None,
        root: str | None = None,
    ) -> str:
        """Synchronize .scope file boundaries against the current AST topology.

        Re-scans the dependency graph and updates each .scope file's includes
        and excludes to match the real imports.  Preserves any lines marked
        with ``# keep`` or ``# manual``.  Non-destructive: context, description,
        keywords, and related fields are never touched.

        Args:
            scopes: Specific scope names to sync (omit for entire repo).
            root: Repository root path (auto-detected if omitted).
        """
        import json
        from ..paths.repo import find_repo_root
        from ..workflows.sync import sync_scopes

        effective_root = root or _root or find_repo_root(_cli_root)
        if effective_root is None:
            return json.dumps({"error": "Could not find repository root"})

        count = sync_scopes(effective_root, scopes)
        return json.dumps({
            "scopes_modified": count,
            "message": f"Synchronized {count} scope(s)." if count else "All scopes already in sync.",
        })
