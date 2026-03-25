# MCP Server Setup

dotscope's primary interface for AI agents is an MCP (Model Context Protocol) server. The agent calls `resolve_scope` to get files and context, and dotscope tracks every call for the feedback loop.

## Install

```bash
pip install dotscope[mcp]
```

This installs the `dotscope-mcp` command.

## Claude Desktop

Edit your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "dotscope-mcp",
      "args": ["--root", "/path/to/your/project"]
    }
  }
}
```

If you omit `--root`, dotscope uses the current working directory.

Restart Claude Desktop after editing the config. You should see "dotscope" listed in the MCP tools panel.

## Claude Code

Claude Code discovers MCP servers from the same config file. The setup is identical to Claude Desktop.

## Cursor

Add to your Cursor MCP config (Settings > MCP Servers):

```json
{
  "dotscope": {
    "command": "dotscope-mcp",
    "args": ["--root", "/path/to/your/project"]
  }
}
```

## Verifying the Connection

Ask your agent: "What scopes are available?" It should call `resolve_scope` or `match_scope` and list the scopes dotscope generated during ingest.

If nothing shows up, check that you've run `dotscope ingest .` in the project first. The MCP server needs a `.scopes` index to know what's available.

## Available Tools

The MCP server exposes these tools to the agent:

**`resolve_scope`** — The primary tool. Takes a scope expression (e.g., `auth`, `auth+payments`, `auth@context`) and returns files, context, attribution hints, accuracy data, health warnings, and near-misses. Supports token budgets.

**`match_scope`** — Given a file path, returns which scope(s) cover it. Useful when an agent knows which file it needs to work on but doesn't know which scope to resolve.

**`get_context`** — Returns only the context field for a scope, without the file list. Lighter than a full resolve when the agent just needs architectural knowledge.

**`impact_analysis`** — Given a file path, returns its transitive dependents (blast radius). Answers: "If I change this file, what else might break?"

**`scope_observations`** — Returns observation data for a scope: recent accuracy, trend, lessons applied. Useful for agents that want to assess how reliable a scope's predictions are.

**`suggest_scope_changes`** — Based on observation data, suggests modifications to a scope's includes or context. The agent can present these to the developer for approval.

**`session_summary`** — Returns a summary of the current agent session: scopes resolved, tokens served, reduction ratio, attribution hints served. Call at the end of a task.

**`ingest_codebase`** — Triggers a full ingest from within the agent. Returns the discovery report programmatically: implicit contracts found, cross-cutting hubs, volatility surprises, token reduction, and per-scope recall.

## The Resolve Response

A typical `resolve_scope` response:

```json
{
  "scope": "auth/",
  "files": ["auth/handler.py", "auth/tokens.py", "models/user.py"],
  "context": "JWT tokens with 15-min access / 7-day refresh rotation...",
  "token_count": 1420,

  "attribution_hints": [
    { "hint": "billing.py and webhook_handler.py have 73% co-change rate", "source": "git_history" },
    { "hint": "Never call .delete() on User, use .deactivate()", "source": "hand_authored" }
  ],

  "accuracy": {
    "observations": 12,
    "avg_recall": 0.91,
    "avg_precision": 0.88,
    "trend": "improving",
    "last_observation": "2h ago",
    "lessons_applied": 3
  },

  "health_warnings": [],
  "near_misses": []
}
```

Everything after `token_count` is visibility metadata. The agent naturally references it: "Based on git history analysis, billing.py and webhook_handler.py change together 73% of the time, so I'm including both."

## Session Tracking

Every `resolve_scope` call is tracked. When the MCP server shuts down (agent disconnects), it prints a session summary to stderr:

```
── dotscope session ──────────────────────────────
  3 scopes resolved · 4,200 tokens served (91% reduction)
  2 attribution hints served
  Session tracked → run `dotscope sessions` to review
───────────────────────────────────────────────────
```

## Installing the Post-Commit Hook

For the feedback loop to work, dotscope needs to observe what happens after the agent commits:

```bash
dotscope hook install
```

This adds a git post-commit hook that records which files were changed and compares them against what the scopes predicted. Utility scores update automatically.

## Troubleshooting

**"No scopes found"** — Run `dotscope ingest .` in your project root first.

**Agent doesn't see dotscope tools** — Check that `dotscope-mcp` is on your PATH. Try running it directly in a terminal to see if it starts without errors.

**Stale data after code changes** — Re-run `dotscope ingest .` to regenerate scopes. Or let the feedback loop correct over time if the changes are incremental.

**Permission errors** — The MCP server needs read access to `.scope` files and read/write access to `.dotscope/`. Both should be in your project root.
