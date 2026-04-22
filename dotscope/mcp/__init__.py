"""MCP server for dotscope - the primary agent-facing interface.

Exposes scope resolution, matching, and context as MCP tools
that any MCP-compatible agent can call.

Install: pip install dotscope[mcp]
Run: dotscope-mcp --root /path/to/repo

Configure in Claude Desktop or similar:
{
    "mcpServers": {
        "dotscope": {
            "command": "/full/path/to/dotscope-mcp",
            "args": ["--root", "/path/to/repo"]
        }
    }
}
"""

from __future__ import annotations

import os
import sys

from .. import __version__


def _detect_client() -> str:
    """Best-effort client detection from environment variables."""
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
    import argparse
    import atexit

    verbose_stderr = os.environ.get("DOTSCOPE_MCP_VERBOSE", "0") not in {"", "0", "false", "False"}

    _isolated_stdout = None
    isolation_error = None
    try:
        virgin_stdout_fd = os.dup(1)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
        _isolated_stdout = open(virgin_stdout_fd, "wb", buffering=0)
    except Exception as exc:
        isolation_error = str(exc)
        if verbose_stderr:
            print(f"dotscope warning: stdout isolation failed: {exc}", file=sys.stderr)

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP server requires the 'mcp' package.\n"
            "Install with: pip install dotscope[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default=None, help="Repository root path")
    known, _remaining = parser.parse_known_args()
    _cli_root = known.root or os.environ.get("DOTSCOPE_ROOT")

    mcp = FastMCP("dotscope")
    if _isolated_stdout is not None:
        from io import TextIOWrapper

        import anyio
        from mcp.server.stdio import stdio_server

        _mcp_stdout = anyio.wrap_file(TextIOWrapper(_isolated_stdout, encoding="utf-8"))

        async def _run_stdio_with_isolated_stdout(self_ref=mcp):
            async with stdio_server(stdout=_mcp_stdout) as (read_stream, write_stream):
                await self_ref._mcp_server.run(
                    read_stream,
                    write_stream,
                    self_ref._mcp_server.create_initialization_options(),
                )

        mcp.run_stdio_async = _run_stdio_with_isolated_stdout

    from ..ux.visibility import SessionTracker

    tracker = SessionTracker()
    client_id = _detect_client()
    if hasattr(tracker, "_stats"):
        tracker._stats.client_identifier = client_id

    _root = None
    _repo_tokens = 0
    _cached_history = None
    _cached_graph_hubs = {}
    try:
        from ..engine.parser import parse_scopes_index
        from ..paths.repo import find_repo_root
        from ..storage.cache import load_cached_graph_hubs, load_cached_history

        _root = find_repo_root(_cli_root)
        if _root:
            os.environ["DOTSCOPE_ROOT"] = _root
            _idx_path = os.path.join(_root, ".scopes")
            if os.path.exists(_idx_path):
                _idx = parse_scopes_index(_idx_path)
                _repo_tokens = _idx.total_repo_tokens
            _cached_history = load_cached_history(_root)
            _cached_graph_hubs = load_cached_graph_hubs(_root)
            tracker.set_repo_root(_root)
            os.chdir(_root)
        elif _cli_root:
            os.environ["DOTSCOPE_ROOT"] = os.path.abspath(_cli_root)
    except Exception:
        pass

    def _print_session_summary():
        if os.environ.get("DOTSCOPE_MCP_SESSION_SUMMARY", "0") in {"", "0", "false", "False"}:
            return
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

    if isolation_error and _root:
        try:
            from .logger import get_mcp_logger

            get_mcp_logger().warning("stdout isolation failed: %s", isolation_error)
        except Exception:
            pass

    from .core import register_core_tools
    from .hooks import register_hooks_tools
    from .ingest import register_ingest_tools
    from .observability import register_observability_tools

    shared_kwargs = {
        "tracker": tracker,
        "client_id": client_id,
        "_root": _root,
        "_repo_tokens": _repo_tokens,
        "_cached_history": _cached_history,
        "_cached_graph_hubs": _cached_graph_hubs,
        "_cli_root": _cli_root,
    }
    register_core_tools(mcp, **shared_kwargs)
    register_observability_tools(mcp, **shared_kwargs)
    register_ingest_tools(mcp, **shared_kwargs)
    register_hooks_tools(mcp, **shared_kwargs)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
