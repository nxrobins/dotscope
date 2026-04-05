def register_intents_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _root = kwargs.get('_root')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')
    _cli_root = kwargs.get('_cli_root')

    @mcp.tool()
    def partition_search_space(
        intent: str,
        n_partitions: int = 3,
    ) -> dict:
        """Divide an exploratory task into non-overlapping starting points.

        Uses semantic search to find relevant files, then graph analysis
        to cleave them into decoupled partitions. Scouts assigned to
        different partitions are guaranteed to start in structurally
        independent domains.

        Args:
            intent: Natural language description of what to investigate
            n_partitions: Number of parallel scouts to support (2-10)

        May return fewer partitions than requested if search results
        are highly localized. Check len(partitions), not n_partitions.
        """
        from ..swarm.partition import partition_search_space as _partition
        root = _root or _find_root()
        graph = _get_graph(root)
        index = _load_index(root)
        invariants = _load_invariants(root)
        return _partition(intent, n_partitions, root, graph, index, invariants)

    @mcp.tool()
    def resolve_trace(
        entry_file: str,
        max_depth: int = 3,
        focus: str = "",
    ) -> dict:
        """Resolve context along a specific execution path.

        Follows imports from entry_file up to max_depth. Returns unified
        context covering all scopes crossed, deduplicated, with only the
        constraints relevant to files in the trace.

        Args:
            entry_file: Starting point for the trace
            max_depth: How many import levels to follow (default 3, max 10)
            focus: Optional keyword to filter context relevance
                   (e.g., "memory" to prioritize memory-related context)
        """
        from ..swarm.trace import resolve_trace as _trace
        root = _root or _find_root()
        graph = _get_graph(root)
        index = _load_index(root)
        invariants = _load_invariants(root)
        return _trace(
            entry_file, max_depth, focus or None,
            root, graph, index, invariants,
        )
