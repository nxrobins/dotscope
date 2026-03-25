# dotscope

Your codebase has years of knowledge trapped in git history, scattered docs, and the heads of engineers who've moved on. AI agents see none of it. They start every task blind — reading the wrong files, missing hidden dependencies, breaking rules nobody told them about.

dotscope fixes this. Point it at any codebase and it reverse-engineers the architectural knowledge into `.scope` files that agents read before they write a single line of code. Then it watches what actually happens, learns from every commit, and gets more accurate over time.

Two commands to start:

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
  Trust it: dotscope backtest --commits 500
```

No configuration. No manual file writing. dotscope reads your dependency graph, mines your git history, absorbs your existing docs, backtests against real commits, and auto-corrects what it got wrong.

---

## Three things dotscope does that nothing else does

### 1. It gives agents the right context before they start

Every agent session starts cold. dotscope generates `.scope` files that tell the agent exactly which files matter, which to skip, and the architectural knowledge that isn't in the code — invariants, gotchas, hidden dependencies, stability warnings.

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
related:
  - payments/.scope
  - api/.scope
```

The `context` field is the part that matters most. It carries knowledge that doesn't exist anywhere in the code itself.

### 2. It enforces the rules before mistakes happen

dotscope knows your codebase's implicit contracts (from git history), anti-patterns (from scope context), dependency boundaries (from the import graph), and architectural direction (from your declared intents). It surfaces all of this as **constraints** — before the agent writes code, and again before it commits.

```bash
dotscope check

  HOLD  implicit_contract
    auth/tokens.py modified without api/auth_routes.py (82% co-change)
    Likely needs changes: validate_token(), refresh_handler()
    -> Acknowledge: dotscope check --acknowledge contract_auth_tokens_api_a1b2c3

  NOTE  architectural_intent
    New import from payments/ in auth/handler.py
    Intent: decouple auth/ from payments/ (set 2026-03-20)

dotscope: 1 hold, 1 note — address holds to proceed
```

Holds come with fix proposals. Anti-pattern violations come with exact replacement diffs. The agent can apply them without thinking.

Declare where your codebase is headed:

```bash
dotscope intent add decouple auth/ payments/ --reason "Separate concerns"
dotscope intent add freeze core/                # Changes require acknowledgment
dotscope intent add deprecate utils/legacy.py --replacement utils/helpers.py
```

Rules that are consistently wrong self-correct — acknowledged holds decay in confidence over time.

### 3. It learns from every commit

Most tools generate once and rot. dotscope closes a feedback loop:

```
Agent resolves a scope (the prediction)
  → Agent works, commits
    → Post-commit hook records what actually happened (the observation)
      → Utility scores update, constraints refine
        → Next resolution is more accurate
```

After enough observations, dotscope knows which files agents actually use (utility scoring), which patterns keep recurring (lessons), and which boundaries have never been crossed (invariants). It feeds all of this back into every subsequent resolution.

Install with `dotscope hook install`.

---

## What the agent actually receives

Every `resolve_scope` call returns files, context, and structured metadata the agent weaves into its reasoning:

```json
{
  "files": ["auth/handler.py", "auth/tokens.py", "models/user.py"],
  "context": "JWT tokens with 15-min access / 7-day refresh...",
  "token_count": 1420,

  "constraints": [
    { "category": "contract", "message": "If you modify auth/tokens.py, review api/auth_routes.py", "confidence": 0.82 },
    { "category": "anti_pattern", "message": "Use .deactivate() instead of .delete() on User", "confidence": 1.0 }
  ],

  "attribution_hints": [
    { "hint": "billing.py and webhook_handler.py have 73% co-change rate", "source": "git_history" },
    { "hint": "Never call .delete() on User, use .deactivate()", "source": "hand_authored" }
  ],

  "accuracy": {
    "observations": 12, "avg_recall": 0.91, "trend": "improving",
    "last_observation": "2h ago", "lessons_applied": 3
  }
}
```

**Constraints** — the rules. Contracts, anti-patterns, boundaries, intents. Prevention, not correction.

**Attribution hints** — where the knowledge came from. Git history and hand-authored warnings carry different weight.

**Accuracy** — how well this scope predicts what agents actually need. Self-reported. Auditable.

---

## MCP server

The primary interface for agents. Every resolution is tracked.

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

Tools: `resolve_scope`, `match_scope`, `get_context`, `impact_analysis`, `dotscope_check`, `dotscope_acknowledge`, `session_summary`, `suggest_scope_changes`.

## CLI

```bash
dotscope ingest .                          # Enter any codebase
dotscope resolve auth --budget 4000        # Files + context within token budget
dotscope resolve auth+payments             # Compose scopes (union, subtract, intersect)
dotscope check                             # Validate staged changes against rules
dotscope check --backtest                  # What would checks have caught?
dotscope intent add freeze core/           # Declare architectural direction
dotscope impact auth/tokens.py             # Blast radius before touching a file
dotscope health                            # Staleness, drift, coverage gaps
dotscope hook install                      # Start the feedback loop
```

## Docs

- [How It Works](docs/how-it-works.md) — ingest pipeline, feedback loop, backtest validation
- [The .scope File](docs/scope-file.md) — fields, editing, signal comments, the .scopes index
- [MCP Server Setup](docs/mcp-setup.md) — Claude Desktop, Claude Code, Cursor, troubleshooting

## Details

**Zero dependencies** in the base install. Python 3.9+. Cross-platform (macOS, Linux, Windows). Optional extras: `mcp` for the agent server.

**No lock-in.** `.scope` files are plain YAML. `.dotscope/` is gitignored and rebuildable from event logs via `dotscope rebuild`.

**221 tests.** Every feature validated. Every edge case covered.

**Lineage.** `.gitignore` → what to skip. `.env` → what to configure. `.scope` → what to understand.

## License

MIT
