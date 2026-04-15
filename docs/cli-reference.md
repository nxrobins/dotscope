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

## Core Commands

```bash
# Discovery & resolution
dotscope resolve auth                  # Resolve a scope to files + context
dotscope resolve auth --budget 4000    # With token budget
dotscope resolve auth+payments         # Scope composition (union)
dotscope context auth                  # Context only (no files)
dotscope match "fix the auth bug"      # Find matching scope for a task

# Listing
dotscope list                          # List all scopes (alias for list_scopes)
dotscope stats                         # Token savings report
dotscope tree                          # Visual tree of scope relationships
```

## Ingest & Sync

```bash
dotscope ingest .                      # Full codebase ingest
dotscope ingest src/auth               # Single module
dotscope ingest . --max-commits 500    # Deeper history mining
dotscope ingest . --dry-run            # Preview without writing
dotscope ingest . --quiet              # Suppress progress (for CI)
dotscope ingest . --no-history         # Skip git history mining
dotscope ingest . --no-docs            # Skip doc absorption

dotscope sync                          # Re-align all .scope boundaries against AST
dotscope sync auth payments            # Sync specific scopes only
dotscope refresh                       # Reload runtime cache from disk
```

## Enforcement & Verification

```bash
dotscope check                         # Validate staged changes
dotscope check --diff "$(git diff)"    # Validate a specific diff
dotscope check --backtest              # Backtest against git history
dotscope check --explain               # Include full provenance for findings

dotscope backtest                      # Validate scopes against recent history
dotscope backtest --commits 100        # Custom commit range
```

## Conventions & Voice

```bash
dotscope conventions                   # List all conventions + compliance
dotscope conventions --discover        # Discover patterns from codebase
dotscope diff --staged                 # Semantic diff against conventions

dotscope voice                         # Show discovered code voice
```

## Analysis

```bash
dotscope health                        # Staleness, coverage gaps, drift
dotscope validate                      # Check .scope files for broken paths
dotscope impact auth/tokens.py         # Predict blast radius of changes
dotscope utility auth                  # Show utility scores for a scope
```

## Hooks

```bash
dotscope hook install                  # Pre-commit + post-commit hooks
dotscope hook claude                   # Claude Code pre-commit hook
dotscope hook status                   # Check what's installed
dotscope hook uninstall                # Remove hooks
```

## Debugging

```bash
dotscope debug --last                  # Bisect the last bad session
dotscope debug <session_id>            # Bisect a specific session
dotscope debug --list                  # List recent sessions
```

## MCP Server

For agents, add the MCP server to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "dotscope": { "command": "dotscope-mcp" }
  }
}
```

`dotscope init` configures this automatically for Claude Desktop, Claude Code, and Cursor. See [MCP Integration Guide](mcp-integration.md) for the full tools reference.
