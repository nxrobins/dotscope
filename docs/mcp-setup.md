# MCP Server Setup

dotscope's primary interface for agents is an MCP server. The agent calls `resolve_scope` to get files, context, and constraints. dotscope tracks every call for the feedback loop.

## Install

```bash
pip install dotscope[mcp]
```

## Claude Desktop

Edit your config file:

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

Omit `--root` to use the current working directory. Restart Claude Desktop after editing.

## Claude Code

Same config file as Claude Desktop.

## Cursor

Settings > MCP Servers:

```json
{
  "dotscope": {
    "command": "dotscope-mcp",
    "args": ["--root", "/path/to/your/project"]
  }
}
```

## Verifying

Ask your agent: "What scopes are available?" It should call `list_scopes` and show what dotscope generated during ingest.

## Available Tools

### Resolution

**`resolve_scope`** — The primary tool. Takes a scope expression and optional token budget. Returns files, context, constraints, attribution hints, accuracy, health warnings, and near-misses. Supports a `task` parameter for relevance-ranked constraints.

**`match_scope`** — Given a task description, returns which scope(s) are most relevant.

**`get_context`** — Context only, no files. Lighter than a full resolve.

**`list_scopes`** — All available scopes with descriptions.

### Analysis

**`impact_analysis`** — Transitive blast radius for a file.

**`scope_observations`** — Accuracy history and trends for a scope.

**`suggest_scope_changes`** — Data-driven suggestions for includes to add or deprioritize.

### Enforcement

**`dotscope_check`** — Validate a diff against codebase rules. Returns holds (must address) and notes (informational), with fix proposals. If no diff is provided, checks staged changes. Accepts a `session_id` for boundary checking.

**`dotscope_acknowledge`** — Acknowledge a hold and proceed. Takes comma-separated IDs and a reason. Repeated acknowledgments decay the constraint's confidence.

### Session

**`session_summary`** — Summary of the current session: scopes resolved, tokens served, constraints applied, counterfactuals (what dotscope prevented).

**`ingest_codebase`** — Trigger a full ingest from within the agent.

## The Resolve Response

```json
{
  "scope": "auth/",
  "files": ["auth/handler.py", "auth/tokens.py", "models/user.py"],
  "context": "JWT tokens with 15-min access / 7-day refresh...",
  "token_count": 1420,

  "constraints": [
    { "category": "contract", "message": "If you modify auth/tokens.py, review api/auth_routes.py", "confidence": 0.82 },
    { "category": "anti_pattern", "message": "Use .deactivate() instead of .delete() on User", "confidence": 1.0 },
    { "category": "intent", "message": "decouple auth/, payments/: separate concerns", "confidence": 1.0 }
  ],

  "attribution_hints": [
    { "hint": "billing.py and webhook_handler.py have 73% co-change rate", "source": "git_history" },
    { "hint": "Never call .delete() on User, use .deactivate()", "source": "hand_authored" }
  ],

  "accuracy": {
    "observations": 12, "avg_recall": 0.91, "trend": "improving",
    "last_observation": "2h ago", "lessons_applied": 3
  },

  "health_warnings": [],
  "near_misses": []
}
```

**`constraints`** — Rules the agent should follow. Implicit contracts, anti-patterns, dependency boundaries, stability warnings, and architectural intents. Filtered to the resolved scope, capped at 5 per category. Prevention, not correction.

**`attribution_hints`** — Where the knowledge came from. `git_history`, `hand_authored`, `signal_comment`, or `graph`. Different credibility registers for different knowledge types.

**`accuracy`** — How well this scope predicts what agents need. Self-reported. Auditable.

## The Check Response

```json
{
  "passed": false,
  "holds": [
    {
      "category": "implicit_contract",
      "severity": "hold",
      "message": "auth/tokens.py modified without api/auth_routes.py (82% co-change)",
      "file": "auth/tokens.py",
      "suggestion": "Review api/auth_routes.py for necessary changes",
      "acknowledge_id": "contract_auth_tokens_api_a1b2c3",
      "proposed_fix": {
        "file": "api/auth_routes.py",
        "reason": "When auth/tokens.py changes, these sections typically need updates",
        "predicted_sections": ["validate_token", "refresh_handler"],
        "confidence": 0.78
      }
    }
  ],
  "notes": [],
  "files_checked": 3
}
```

Holds come with fix proposals. The agent can apply them or acknowledge and proceed.

## Session Summary

On MCP server shutdown (or when the agent calls `session_summary`):

```
── dotscope session ──────────────────────────────
  3 scopes resolved · 4,200 tokens served (91% reduction)

  What dotscope prevented:
    Agent used .deactivate() instead of .delete() on User
      ← auth/ scope context
    Agent included webhook_handler.py alongside billing.py
      ← implicit contract (73% co-change)

  What dotscope provided:
    4 attribution hints served
    3 constraints applied
───────────────────────────────────────────────────
```

Counterfactuals appear after 3+ observations (needs data to be meaningful).

## Post-Commit Hook

For the feedback loop:

```bash
dotscope hook install
```

Adds a git post-commit hook that records what changed and compares it to what was predicted. Utility scores update automatically. Near-misses are detected. Works on macOS, Linux, and Windows.

## Troubleshooting

**"No scopes found"** — Run `dotscope ingest .` first.

**Agent doesn't see tools** — Check that `dotscope-mcp` is on your PATH. Run it directly to check for import errors.

**Stale data** — Re-run `dotscope ingest .` or let the feedback loop correct over time.

**Windows encoding errors** — dotscope uses UTF-8 everywhere with ASCII fallbacks for cp1252 terminals.
