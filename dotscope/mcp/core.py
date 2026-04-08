import json
import os
import time as _time
from typing import Optional
from .middleware import mcp_tool_route
from .pipelines import get_standard_resolve_pipeline

def register_core_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')

    @mcp.tool()
    @mcp_tool_route
    def resolve_scope(
        scope: str,
        budget: Optional[int] = None,
        follow_related: bool = True,
        format: str = "json",
        task: Optional[str] = None,
        root: Optional[str] = None, # Injected by middleware
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
        """
        pipeline = get_standard_resolve_pipeline()
        initial_state = {
            "root": root,
            "scope": scope,
            "budget": budget,
            "follow_related": follow_related,
            "format": format,
            "task": task,
            "tracker": tracker,
            "_repo_tokens": _repo_tokens,
            "_cached_history": _cached_history,
            "_cached_graph_hubs": _cached_graph_hubs,
            "_resolve_start": _time.perf_counter()
        }
        
        final_state = pipeline.execute(initial_state)

        if "halt_error" in final_state:
            return final_state["halt_error"]

        if format == "json":
            return json.dumps(final_state.get("data", {}), indent=2)
        return final_state.get("raw_output", "")

    @mcp.tool()
    @mcp_tool_route
    def match_scope(task: str, root: Optional[str] = None) -> str:
        """Find the most relevant scope(s) for a task description.

        Uses keyword overlap between the task and scope keywords/tags/descriptions.
        Returns a ranked list with confidence scores.

        Args:
            task: Natural language description of what you're working on
        """
        from ..engine.discovery import load_resolution_index, load_resolution_scopes
        from ..engine.matcher import match_task

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
            "matches": [{"scope": name, "confidence": round(score, 3)} for name, score in matches],
            "task": task,
        }, indent=2)

    @mcp.tool()
    @mcp_tool_route
    def get_context(scope: str, section: Optional[str] = None, root: Optional[str] = None) -> str:
        """Get architectural context for a scope without loading any files.

        This is the knowledge that isn't in the code itself: invariants,
        gotchas, conventions, architectural decisions.

        Args:
            scope: Scope name or path
            section: Optional section name to filter (e.g., "invariants", "gotchas")
        """
        from ..engine.discovery import find_resolution_scope
        from ..engine.context import query_context
        from ..workflows.refresh import ensure_resolution_freshness

        if root:
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
    @mcp_tool_route
    def list_scopes(root: Optional[str] = None) -> str:
        """List all available scopes with descriptions, tags, and token estimates.

        Searches the .scopes index and/or walks the directory tree for .scope files.
        """
        from ..engine.discovery import load_resolution_index, load_resolution_scopes

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
