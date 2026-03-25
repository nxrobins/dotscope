# dotscope

Your codebase has years of knowledge trapped in git history, scattered docs, and the heads of engineers who've moved on. AI agents see none of it. They start every task blind — reading the wrong files, missing hidden dependencies, breaking rules nobody told them about.

dotscope fixes this. Point it at any codebase and it reverse-engineers the architectural knowledge into `.scope` files that agents read before they write a single line of code. Then it watches what actually happens, learns from every commit, enforces the rules, and tells you what it prevented.

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

## What dotscope does

### 1. Right context before the agent starts

Every agent session starts cold. dotscope generates `.scope` files that tell the agent which files matter, which to skip, and the architectural knowledge that isn't in the code.

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
assertions:
  ensure_includes: [models/user.py]
  ensure_context_contains: ["soft deletes"]
```

The `context` field carries knowledge that doesn't exist in the code. The `assertions` field guarantees critical files are never silently dropped by token budgeting — if `models/user.py` can't fit, dotscope raises an error instead of serving incomplete context.

### 2. Rule enforcement before mistakes happen

dotscope surfaces constraints before the agent writes code, and validates changes before the agent commits.

```bash
dotscope check

  HOLD  implicit_contract
    auth/tokens.py modified without api/auth_routes.py (82% co-change)
    Likely needs changes: validate_token(), refresh_handler()

  NOTE  architectural_intent
    New import from payments/ in auth/handler.py
    Intent: decouple auth/ from payments/ (set 2026-03-20)

dotscope: 1 hold, 1 note — address holds to proceed
```

Six check categories. Holds come with fix proposals. Anti-pattern violations come with exact replacement diffs.

Declare architectural direction:

```bash
dotscope intent add decouple auth/ payments/ --reason "Separate concerns"
dotscope intent add freeze core/
dotscope intent add deprecate utils/legacy.py --replacement utils/helpers.py
```

### 3. Learning from every commit

Most tools generate once and rot. dotscope closes a feedback loop:

```
Agent resolves a scope (prediction)
  → Agent works, commits
    → Post-commit hook records what actually happened (observation)
      → Utility scores update, constraints refine, sessions freeze as regression tests
        → Next resolution is more accurate
```

At session end, dotscope shows what it prevented:

```
── dotscope session ──────────────────────────────
  3 scopes resolved · 4,200 tokens served (91% reduction)

  What dotscope prevented:
    Agent used .deactivate() instead of .delete() on User
      ← auth/ scope context
    Agent included webhook_handler.py alongside billing.py
      ← implicit contract (73% co-change)
───────────────────────────────────────────────────
```

### 4. Compiler-grade rigor

dotscope treats context resolution like compilation. If it silently resolves wrong context, the agent doesn't crash — it writes subtly incorrect code and nobody knows why.

**Assertions** guarantee critical files and context survive budget cuts. Violations are hard errors, not silent drops.

**Regression suite** auto-freezes successful sessions as test cases. `dotscope test-compiler` replays them after algorithm changes — dropped files are regressions.

**Benchmarking** proves it works with numbers: token efficiency, hold rate, compilation speed, scope health.

**Context bisection** debugs bad sessions deterministically: `dotscope debug --last` bisects files, context, and constraints to find whether the issue was a resolution gap, constraint gap, agent ignoring context, or context conflict. Zero LLM calls.

---

## What the agent receives

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

---

## MCP server

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

Tools: `resolve_scope`, `match_scope`, `get_context`, `impact_analysis`, `dotscope_check`, `dotscope_acknowledge`, `dotscope_debug`, `session_summary`.

## CLI

```bash
# Context
dotscope ingest .                          # Enter any codebase
dotscope resolve auth --budget 4000        # Files + context within token budget
dotscope resolve auth+payments             # Compose scopes

# Enforcement
dotscope check                             # Validate staged changes
dotscope check --backtest                  # Prove it catches real mistakes
dotscope intent add freeze core/           # Declare architectural direction

# Rigor
dotscope test-compiler                     # Regression suite
dotscope bench                             # Performance metrics
dotscope debug --last                      # Bisect a bad session

# Maintenance
dotscope impact auth/tokens.py             # Blast radius
dotscope health                            # Staleness, drift, coverage
dotscope hook install                      # Start the feedback loop
```

## Docs

- [How It Works](docs/how-it-works.md) — ingest, enforcement, feedback loop, rigor
- [The .scope File](docs/scope-file.md) — fields, assertions, anti-patterns, intent
- [MCP Server Setup](docs/mcp-setup.md) — setup, all tools, troubleshooting

## Details

**Zero dependencies** in the base install. Python 3.9+. Cross-platform. Optional extras: `mcp` for the agent server.

**No lock-in.** `.scope` files are plain YAML. `.dotscope/` is gitignored and rebuildable via `dotscope rebuild`.

**266 tests.** Every feature validated.

**Lineage.** `.gitignore` → what to skip. `.env` → what to configure. `.scope` → what to understand.

## License

MIT
