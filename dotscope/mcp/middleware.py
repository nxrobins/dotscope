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

        # Inject repository root dynamically
        root = find_repo_root()
        if not root:
            err_msg = "Could not find repository root"
            logger.warning(f"Aborted MCP execution for '{func.__name__}': {err_msg}")
            return json.dumps({"error": err_msg})
            
        kwargs["root"] = root

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
                "error": "Internal Agent Interface Check Failure",
                "message": f"MCP Module execution aborted. Diagnostics written to .dotscope/mcp_debug.log.",
                "details": str(e)
            }, indent=2)
            
    return wrapper
