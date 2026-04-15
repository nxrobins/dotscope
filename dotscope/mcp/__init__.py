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

from .. import __version__


def _detect_client() -> str:
    """Best-effort client detection from environment variables.

    # TODO: validate env vars for Windsurf, Zed, Codex CLI, JetBrains
    # against real installations. Long-term: read clientInfo from MCP
    # initialize handshake when FastMCP exposes it.
    """
    env = os.environ
    if "CLAUDE_VERSION" in env or "CLAUDE_DESKTOP" in env:
        return "claude-desktop"
    if env.get("CLAUDE_CODE"):
        return "claude-code"
    if env.get("TERM_PROGRAM") == "Cursor":
        return "cursor"
    if "WINDSURF" in env or "CODEIUM" in env:
        return "windsurf"
    if env.get("TERM_PROGRAM") == "vscode":
        return "vscode"
    if "ZED_TERM" in env or env.get("TERM_PROGRAM") == "zed":
        return "zed"
    if "JETBRAINS" in env or "IDEA" in env.get("TERMINAL_EMULATOR", ""):
        return "jetbrains"
    if env.get("CODEX_CLI"):
        return "codex-cli"
    return "unknown"


def main():
    """MCP server entry point."""
    import os
    import sys
    import contextlib

    # Redirect stray stdout writes (from libraries, print() calls, etc.)
    # to stderr so that only clean JSON-RPC flows over the stdio transport.
    #
    # How it works:
    #   1. Save the real stdout fd (the MCP pipe to the client).
    #   2. Point fd 1 and sys.stdout at stderr (captures stray output).
    #   3. Build an isolated file object from the saved fd.
    #   4. Patch the reference that FastMCP.run_stdio_async actually uses
    #      — the local name imported via `from mcp.server.stdio import
    #      stdio_server` inside mcp/server/fastmcp/server.py.  Patching
    #      `mcp.server.stdio.stdio_server` alone has no effect because
    #      the `from … import` already bound a direct reference.
    _isolated_stdout = None
    try:
        virgin_stdout_fd = os.dup(1)
        os.dup2(2, 1)                    # fd 1 → stderr
        sys.stdout = sys.stderr           # Python-level sync

        _isolated_stdout = open(virgin_stdout_fd, "wb", buffering=0)
    except Exception as e:
        print(f"dotscope warning: stdout isolation failed: {e}", file=sys.stderr)

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

    # Patch the stdio_server reference that FastMCP.run_stdio_async actually
    # calls.  The module does `from mcp.server.stdio import stdio_server` so
    # we must overwrite that *local* name, not the module-level attribute.
    if _isolated_stdout is not None:
        try:
            import mcp.server.stdio as _mcp_stdio
            import mcp.server.fastmcp.server as _fastmcp_mod
            import anyio
            from io import TextIOWrapper

            _original_stdio_server = _mcp_stdio.stdio_server

            @contextlib.asynccontextmanager
            async def _patched_stdio_server(stdin=None, stdout=None):
                if stdout is None:
                    stdout = anyio.wrap_file(
                        TextIOWrapper(_isolated_stdout, encoding="utf-8")
                    )
                async with _original_stdio_server(stdin=stdin, stdout=stdout) as streams:
                    yield streams

            # Patch both: the module attr (for anyone else importing it) and
            # the local name inside fastmcp.server (the one that matters).
            _mcp_stdio.stdio_server = _patched_stdio_server
            _fastmcp_mod.stdio_server = _patched_stdio_server
        except Exception as e:
            print(f"dotscope warning: stdio patch failed: {e}", file=sys.stderr)

    mcp = FastMCP("dotscope")

    # Session-level tracker (lives across tool calls in a single MCP session)
    from ..ux.visibility import SessionTracker
    tracker = SessionTracker()
    
    client_id = _detect_client()
    
    if hasattr(tracker, "_stats"):
        tracker._stats.client_identifier = client_id
    _root = None  # Will be set below

    # Load cached data from .dotscope/ for attribution hints + session stats
    _repo_tokens = 0
    _cached_history = None
    _cached_graph_hubs = {}
    try:
        from ..paths.repo import find_repo_root
        from ..engine.parser import parse_scopes_index
        from ..storage.cache import load_cached_history, load_cached_graph_hubs
        _root = find_repo_root(_cli_root)
        if _root:
            _idx_path = os.path.join(_root, ".scopes")
            if os.path.exists(_idx_path):
                _idx = parse_scopes_index(_idx_path)
                _repo_tokens = _idx.total_repo_tokens
            _cached_history = load_cached_history(_root)
            _cached_graph_hubs = load_cached_graph_hubs(_root)
            tracker.set_repo_root(_root)
            os.chdir(_root)
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
            from ..storage.near_miss import save_session_scopes
            scopes = list(tracker._stats.unique_scopes)
            if scopes and _root:
                save_session_scopes(_root, scopes)
        except Exception:
            pass


    atexit.register(_print_session_summary)
    atexit.register(_save_session_scopes)

    from .core import register_core_tools
    from .observability import register_observability_tools
    from .ingest import register_ingest_tools
    from .hooks import register_hooks_tools
    register_core_tools(mcp, tracker=tracker, client_id=client_id, _root=_root, _repo_tokens=_repo_tokens, _cached_history=_cached_history, _cached_graph_hubs=_cached_graph_hubs, _cli_root=_cli_root)
    register_observability_tools(mcp, tracker=tracker, client_id=client_id, _root=_root, _repo_tokens=_repo_tokens, _cached_history=_cached_history, _cached_graph_hubs=_cached_graph_hubs, _cli_root=_cli_root)
    register_ingest_tools(mcp, tracker=tracker, client_id=client_id, _root=_root, _repo_tokens=_repo_tokens, _cached_history=_cached_history, _cached_graph_hubs=_cached_graph_hubs, _cli_root=_cli_root)
    register_hooks_tools(mcp, tracker=tracker, client_id=client_id, _root=_root, _repo_tokens=_repo_tokens, _cached_history=_cached_history, _cached_graph_hubs=_cached_graph_hubs, _cli_root=_cli_root)
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
