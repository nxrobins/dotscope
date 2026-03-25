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

  "health_warnings": [],
  "near_misses": []
}
```

**Attribution hints** tell the agent *what matters most* and *where the knowledge came from* — git history analysis vs hand-authored warnings vs graph structure. Different credibility registers for different knowledge types.

**Accuracy** tracks how well this scope predicts what agents actually need. Trend tells you if it's getting better or worse.

**Health warnings** fire when a scope degrades: accuracy dropped >15%, scope file >30 days stale, or uncovered files appeared.

**Near-misses** surface after a commit where the agent avoided an anti-pattern that the scope warned against. The disaster that didn't happen.

## The feedback loop

```
Agent resolves a scope (prediction)
  → Agent works, commits
    → Post-commit hook records what actually happened (observation)
      → Utility scores update, near-misses detected
        → Next resolution is more accurate
```

Install with `dotscope hook install`. Scopes that start as documentation become intelligence.

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

Key tools: `resolve_scope`, `match_scope`, `get_context`, `impact_analysis`, `session_summary`, `suggest_scope_changes`.

## CLI

```bash
dotscope ingest .                          # Enter any codebase
dotscope resolve auth                      # Files the agent should see
dotscope resolve auth --budget 4000        # Best 4K tokens
dotscope resolve auth+payments             # Union
dotscope resolve auth@context              # Knowledge only, no files
dotscope impact auth/tokens.py             # Blast radius
dotscope health                            # Staleness, drift, coverage gaps
dotscope backtest --commits 500            # Validate against history
dotscope hook install                      # Start the feedback loop
```

## Details

**Zero dependencies** in the base install. Python 3.9+. Cross-platform (macOS, Linux, Windows). Optional extras: `mcp` for the agent server.

**No lock-in.** `.scope` files are plain YAML. `.dotscope/` is gitignored and rebuildable via `dotscope rebuild`.

**Lineage.** `.gitignore` → what to skip. `.env` → what to configure. `.scope` → what to understand.

## License

MIT
