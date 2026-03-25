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

dotscope generates `.scope` files that declare what an agent should understand about each part of your codebase: which files matter, which to skip, and the architectural knowledge that isn't in the code. It builds these from your dependency graph, git history, and existing docs. No configuration required.

Then it validates its own output against your commit history and tells you how accurate it is.

## Why it keeps getting better

Most tools stop at generation. dotscope closes a feedback loop:

```
Agent resolves a scope (prediction)
  → Agent works, commits
    → Post-commit hook records what actually happened (observation)
      → Utility scores update, lessons generated
        → Next resolution is more accurate
```

Install the hook with `dotscope hook install`. Scopes that start as documentation become intelligence.

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

The `context` field is the part that matters. It carries knowledge that doesn't exist anywhere in the code itself. dotscope populates it from implicit contracts, stability profiles, docstrings, and signal comments. You can edit it by hand.

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

Key tools: `resolve_scope`, `match_scope`, `get_context`, `impact_analysis`, `scope_observations`, `suggest_scope_changes`. [Full reference →](docs/reference.md)

## CLI quick reference

```bash
dotscope ingest .                          # Enter any codebase
dotscope resolve auth                      # Files the agent should see
dotscope resolve auth --budget 4000        # Best 4K tokens
dotscope resolve auth+payments             # Union
dotscope resolve auth@context              # Knowledge only, no files
dotscope impact auth/tokens.py             # Blast radius
dotscope health                            # Staleness, drift, coverage gaps
dotscope backtest --commits 500            # Validate against history
```

[Full CLI reference →](docs/reference.md)

## Details

**Zero dependencies** in the base install. Python 3.9+. Optional extras: `mcp` for the agent server, `tokens` for accurate token counting.

**No lock-in.** `.scope` files are plain YAML. The `.dotscope/` state directory is gitignored and fully rebuildable from event logs via `dotscope rebuild`.

**Lineage.** `.gitignore` tells git what to skip. `.env` tells your app what to configure. `.scope` tells your agent what to understand.

## License

MIT
