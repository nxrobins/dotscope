import json
import functools
from typing import Callable, Any
from .logger import get_mcp_logger
from ..paths.repo import find_repo_root

def mcp_tool_route(func: Callable[..., Any]) -> Callable[..., str]:
    """A bulletproof interceptor for MCP backend tools.
    
    1. Locates and provisions the `repo_root` dynamically.
    2. Executes the decorated business logic passing the `root` argument.
    3. Catches all Unhandled Exceptions formatting them correctly into Safe JSON models, 
       while routing stack traces strictly into `.dotscope/mcp_debug.log`.
    4. Automatically standardizes the responses to JSON `str`.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> str:
        logger = get_mcp_logger()
        logger.debug(f"Executing MCP Tool: {func.__name__} {args} {kwargs}")

        # Respect an explicit root from the caller before falling back to discovery.
        root = kwargs.get("root") or find_repo_root()
        if not root:
            err_msg = "Could not find repository root"
            logger.warning(f"Aborted MCP execution for '{func.__name__}': {err_msg}")
            return json.dumps({"error": err_msg})
            
        kwargs["root"] = root
        
        # Log to the real-time Mission Control feed
        try:
            import time
            import os
            from pathlib import Path
            activity_path = Path(root) / ".dotscope" / "mcp_activity.jsonl"
            
            # Simple sanitize formatting for the UI
            target_str = str(kwargs)
            if "task_description" in kwargs:
                target_str = f"Task: {kwargs['task_description'][:30]}..."
            elif "scope" in kwargs:
                target_str = f"Scope: ({kwargs.get('scope')})"
            elif "task" in kwargs:
                target_str = f"Task: {kwargs['task'][:30]}..."
            elif "query" in kwargs:
                target_str = f"Query: <{kwargs['query']}>"
            elif "primary_files" in kwargs:
                 target_str = f"Locks: {len(kwargs['primary_files'])} targets"
            
            activity = {
                "ts": int(time.time() * 1000),
                "tool": func.__name__.replace('mcp_dotscope_', ''),
                "target": target_str
            }
            with open(activity_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(activity) + "\n")
        except Exception:
            pass
        
        # MVCC Read-Plane Enforcement
        try:
            from .mvcc import apply_mvcc_to_kwargs
            apply_mvcc_to_kwargs(root, kwargs)
        except Exception as e:
            logger.warning(f"Failed to cleanly apply MVCC semaphores: {e}")

        try:
            result = func(*args, **kwargs)
            # Support handlers returning pre-serialized JSON explicitly, or dicts perfectly
            if isinstance(result, str):
                return result
            # Standard auto-serializer
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception(f"FATAL Exception in MCP Tool Handler '{func.__name__}': {str(e)}")
            return json.dumps({
                "error": "Execution Fault (Recoverable)",
                "message": "The tool encountered an unexpected structural exception. DO NOT abort your overarching task. System diagnostics have been logged safely. You should gracefully self-correct by broadening your search parameters, simplifying your query, or trying an alternate discovery path.",
                "details": str(e)
            }, indent=2)
            
    return wrapper
