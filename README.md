# dotscope

A self-correcting context engine for AI coding agents.

```bash
pip install dotscope
dotscope ingest .
```

```
dotscope scanned 43 files across 7 modules.

⚡ Discoveries

  Hidden dependencies (from 200 commits of git history):
    billing.py → webhook_handler.py    73% co-change, undocumented
    auth/handler.py → cache/sessions.py  68% co-change, undocumented

  Cross-cutting hub:
    models/user.py is imported by 14 files across 5 modules
    A change here affects 23 files transitively

  Volatility surprise:
    config/settings.py — 47 commits, 380 lines changed
    Most changed file in the repo. No .scope context exists for it.

📊 Validation

  Backtested against 200 recent commits:
  Overall recall: 91% — scopes would have given agents the right files
  Token reduction: 88% — from ~47,000 to ~4,200 average per resolution

  auth/    ████████░░ 93% recall
  api/     █████████░ 96% recall
  payments ███████░░░ 71% recall ← needs attention

📁 Created 7 .scope files + .scopes index

  Try it:  dotscope resolve auth
  See it:  dotscope resolve auth --json --budget 4000
  Trust it: dotscope backtest --commits 500
```

## What it does

Every agent session starts cold. No memory of why things are the way they are, what's fragile, what's safe to change.

dotscope generates `.scope` files from your dependency graph, git history, and existing docs. Each one declares what an agent should understand about a module: which files matter, which to skip, and the architectural knowledge that isn't in the code. No configuration required.

Then it watches what actually happens. After every commit, it compares its prediction to reality, updates utility scores, and gets more accurate over time.

## What the agent sees

Every `resolve_scope` response includes visibility metadata the agent naturally weaves into its reasoning:

```json
{
  "files": ["auth/handler.py", "auth/tokens.py", "models/user.py"],
  "context": "JWT tokens with 15-min access / 7-day refresh...",
  "token_count": 1420,

  "attribution_hints": [
    { "hint": "billing.py and webhook_handler.py have 73% co-change rate", "source": "git_history" },
    { "hint": "Never call .delete() on User, use .deactivate()", "source": "hand_authored" }
  ],

  "accuracy": {
    "observations": 12, "avg_recall": 0.91, "trend": "improving",
    "last_observation": "2h ago", "lessons_applied": 3
  },

  "constraints": [
    { "category": "contract", "message": "If you modify auth/tokens.py, review api/auth_routes.py", "confidence": 0.82 },
    { "category": "anti_pattern", "message": "Use .deactivate() instead of .delete() on User", "confidence": 1.0 },
    { "category": "intent", "message": "decouple auth/, payments/: Auth should not depend on payment internals", "confidence": 1.0 }
  ],

  "health_warnings": [],
  "near_misses": []
}
```

**Constraints** are the rules the agent should follow — implicit contracts from git history, anti-patterns from scope context, dependency boundaries from the import graph, and architectural intents declared by the developer. Prevention, not correction.

**Attribution hints** tell the agent *where the knowledge came from* — git history vs hand-authored vs graph structure.

**Accuracy** tracks prediction quality. Trend tells you if it's getting better or worse.

## The feedback loop

```
Agent resolves a scope (prediction)
  → Agent works, commits
    → Post-commit hook records what actually happened (observation)
      → Utility scores update, near-misses detected
        → Next resolution is more accurate
```

Install with `dotscope hook install`. Scopes that start as documentation become intelligence.

## Enforcement

dotscope knows the rules of your codebase. It can enforce them.

```bash
dotscope check                             # Validate staged changes
dotscope check --backtest --commits 10     # What would checks have caught?
dotscope intent add decouple auth/ payments/ --reason "Separate concerns"
dotscope intent add freeze core/           # No changes without acknowledgment
dotscope intent list
```

Three severity levels: **HOLD** (must address or acknowledge), **NOTE** (informational), **CLEAR** (implicit, never shown).

Six check categories: boundary violations, implicit contracts, anti-patterns, dependency direction, stability concerns, architectural intent.

The agent calls `dotscope_check` before committing. Holds come with fix proposals — predicted sections that need changes, or exact diffs for anti-pattern replacements.

Acknowledged holds decay in confidence over time. Rules that are consistently wrong get demoted from HOLD to NOTE. The enforcement system self-corrects just like the resolution system.

## The .scope file

```yaml
# auth/.scope
description: Authentication and session management
includes:
  - auth/
  - models/user.py
excludes:
  - auth/tests/fixtures/
context: |
  JWT tokens with 15-min access / 7-day refresh rotation.
  Session store is Redis. User model has soft deletes —
  never call .delete(), use .deactivate().

  ## Gotchas
  OAuth provider config is fragile. Check auth/README.md first.
related:
  - payments/.scope
  - api/.scope
```

The `context` field carries knowledge that doesn't exist anywhere in the code. dotscope populates it from implicit contracts, stability profiles, docstrings, and signal comments. You can edit it by hand.

## MCP server

Primary interface for agents. Every `resolve_scope` call is tracked.

```bash
pip install dotscope[mcp]
dotscope-mcp
```

```json
{
  "mcpServers": {
    "dotscope": { "command": "dotscope-mcp" }
  }
}
```

Key tools: `resolve_scope`, `match_scope`, `get_context`, `impact_analysis`, `dotscope_check`, `dotscope_acknowledge`, `session_summary`, `suggest_scope_changes`.

## CLI

```bash
dotscope ingest .                          # Enter any codebase
dotscope resolve auth                      # Files the agent should see
dotscope resolve auth --budget 4000        # Best 4K tokens
dotscope resolve auth+payments             # Union
dotscope resolve auth@context              # Knowledge only, no files
dotscope impact auth/tokens.py             # Blast radius
dotscope check                             # Validate staged diff against rules
dotscope check --backtest                  # Replay commits against checks
dotscope intent add freeze core/           # Declare architectural direction
dotscope health                            # Staleness, drift, coverage gaps
dotscope backtest --commits 500            # Validate against history
dotscope hook install                      # Start the feedback loop
```

## Docs

- [How It Works](docs/how-it-works.md) — ingest pipeline, feedback loop, backtest validation
- [The .scope File](docs/scope-file.md) — fields, editing, signal comments, the .scopes index
- [MCP Server Setup](docs/mcp-setup.md) — Claude Desktop, Claude Code, Cursor, troubleshooting

## Details

**Zero dependencies** in the base install. Python 3.9+. Cross-platform (macOS, Linux, Windows). Optional extras: `mcp` for the agent server.

**No lock-in.** `.scope` files are plain YAML. `.dotscope/` is gitignored and rebuildable via `dotscope rebuild`.

**Lineage.** `.gitignore` → what to skip. `.env` → what to configure. `.scope` → what to understand.

## License

MIT
