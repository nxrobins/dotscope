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

Add to your project's `.claude/settings.json` or the global settings:

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "dotscope-mcp"
    }
  }
}
```

No `--root` needed. Claude Code launches from the project directory.

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

### Debugging

**`dotscope_debug`** — Bisect a bad session to find root cause. Deterministic analysis of files, context, and constraints. Returns diagnosis (resolution_gap, constraint_gap, agent_ignored, context_conflict) with recommendations. If no session_id, debugs the most recent bad session.

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
    { "category": "intent", "message": "decouple auth/, payments/: separate concerns", "confidence": 1.0 },
    { "category": "convention", "message": "Convention 'Repository': Must implement get, save; Do not import flask", "confidence": 0.85 }
  ],

  "attribution_hints": [
    { "hint": "billing.py and webhook_handler.py have 73% co-change rate", "source": "git_history" },
    { "hint": "Never call .delete() on User, use .deactivate()", "source": "hand_authored" }
  ],

  "accuracy": {
    "observations": 12, "avg_recall": 0.91, "trend": "improving",
    "last_observation": "2h ago", "lessons_applied": 3
  },

  "routing": [
    { "category": "routing", "message": "Files here follow the 'Repository' convention. Implement: get, save. Do not import: flask.", "confidence": 0.85 },
    { "category": "routing", "message": "Code style: Type hints on most functions (62% adoption). Google style docstrings.", "confidence": 0.9 }
  ],

  "voice": {
    "mode": "adaptive",
    "global": "Type hints on most functions (62% adoption). Follow existing patterns..."
  },

  "health_warnings": [],
  "near_misses": []
}
```

**`constraints`** — Warnings about what NOT to do. Implicit contracts, anti-patterns, boundaries, intents. Capped at 5 per category.

**`routing`** — Guidance about what TO do. Convention blueprints, voice rules, structural patterns. The bowling bumpers. The agent reads this and writes code that already follows the rules.

**`voice`** — How the codebase writes code. Global style rules plus convention-specific voice with canonical snippet when relevant.

**`attribution_hints`** — Where the knowledge came from. `git_history`, `hand_authored`, `signal_comment`, or `graph`. Different credibility registers for different knowledge types.

**`accuracy`** — How well this scope predicts what agents need. Self-reported. Auditable.

## The Check Response

```json
{
  "passed": true,
  "guards": [],
  "nudges": [
    {
      "category": "implicit_contract",
      "severity": "nudge",
      "message": "auth/tokens.py modified without api/auth_routes.py (82% co-change)",
      "file": "auth/tokens.py",
      "suggestion": "Review api/auth_routes.py for necessary changes",
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

Only GUARDs (frozen modules, deprecated imports) make `passed: false`. NUDGEs are course corrections — the agent sees them and self-corrects. The commit is not blocked.

## Assertion Errors

If a token budget can't fit an asserted file, `resolve_scope` returns an error instead of silently dropping it:

```json
{
  "error": "context_exhaustion",
  "assertion_failed": {
    "type": "ensure_includes",
    "detail": "Budget (4000) cannot fit required file: models/user.py (1200 tokens)",
    "file": "models/user.py",
    "file_tokens": 1200,
    "budget": 4000,
    "reason": "Auth scope is meaningless without the User model"
  },
  "suggestion": "Increase budget to at least 5200 tokens"
}
```

The agent sees this and either increases its budget or reports the constraint to the developer. No silent corruption.

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

## Hooks

```bash
dotscope hook install
```

Installs two git hooks:

| Hook | When | What | Blocks? |
|------|------|------|---------|
| pre-commit | Before every commit | `dotscope check` on staged changes | GUARDs only |
| post-commit | After every commit | `dotscope observe` + `dotscope incremental` | Never |

The pre-commit hook only blocks on GUARDs (frozen modules, deprecated imports). NUDGEs (contracts, conventions, anti-patterns) print guidance but pass through. The agent sees the nudge, self-corrects on the next iteration. The rules make the agent faster, not slower.

The post-commit hook records what changed and compares it to what was predicted. Utility scores update automatically. This is the feedback loop that makes dotscope smarter over time.

For Claude Code, an additional hook intercepts commits at the tool level:

```bash
dotscope hook claude     # Claude Code PreToolUse hook (.claude/settings.json)
```

This is a defense-in-depth layer. The git pre-commit hook is sufficient for most setups.

## Troubleshooting

**"No scopes found"** — Run `dotscope ingest .` first. If you resolve a specific module, dotscope will lazy-ingest it on demand (2-3 seconds).

**Agent doesn't see tools** — Check that `dotscope-mcp` is on your PATH. Run it directly to check for import errors.

**Stale data** — Scopes update incrementally on every commit via the post-commit hook. For full re-scan (transitive deps, convention discovery), run `dotscope ingest .`.

**Windows encoding errors** — dotscope uses UTF-8 everywhere with ASCII fallbacks for cp1252 terminals.
