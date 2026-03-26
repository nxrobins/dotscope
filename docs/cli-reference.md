# CLI Reference

## Setup

```bash
pip install dotscope
dotscope init
```

`dotscope init` does everything: ingest, hook install, MCP config for detected IDEs. One command.

For manual setup or re-runs:

```bash
dotscope ingest .               # Full re-ingest
dotscope hook install           # Re-install hooks
```

## Commands

```bash
# Context
dotscope resolve auth --budget 4000
dotscope resolve auth+payments

# Routing verification
dotscope check
dotscope check --backtest
dotscope intent add freeze core/

# Conventions
dotscope conventions                  # List all conventions + compliance
dotscope conventions --discover       # Discover patterns from codebase
dotscope diff --staged                # Semantic diff against conventions

# Voice
dotscope voice                        # Show discovered voice config
dotscope voice --upgrade typing       # Tighten enforcement as codebase improves

# Rigor
dotscope test-compiler
dotscope bench
dotscope debug --last

# Hooks
dotscope hook install             # Pre-commit routing + post-commit feedback
dotscope hook claude              # Claude Code pre-commit hook (defense-in-depth)
dotscope hook status              # Check what's installed

# Maintenance
dotscope health
dotscope impact auth/tokens.py
```

## MCP Server

For agents, add the MCP server:

```json
{
  "mcpServers": {
    "dotscope": { "command": "dotscope-mcp" }
  }
}
```

`dotscope init` configures this automatically for Claude Desktop, Claude Code, and Cursor.
