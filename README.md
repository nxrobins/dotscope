# dotscope

Point it at any codebase. It reads your dependency graph, mines your git history, and tells you things about your own code you didn't know.

```bash
pip install dotscope
dotscope ingest .
```

```
⚡ Discoveries

  Hidden dependencies (from 200 commits):
    billing.py → webhook_handler.py    73% co-change, undocumented
    auth/handler.py → cache/sessions.py  68% co-change, undocumented

  Cross-cutting hub:
    models/user.py imported by 14 files across 5 modules
    A change here affects 23 files transitively

  Volatility surprise:
    config/settings.py — 47 commits, 380 lines changed
    Most changed file in the repo. No documentation exists for it.

📊 Backtested against 200 recent commits:
  Overall recall: 91% — scopes would have given agents the right files
  Token reduction: 88% — from ~47,000 to ~4,200 per resolution

  auth/    ████████░░ 93%
  api/     █████████░ 96%
  payments ███████░░░ 71% ← needs attention
```

That's your codebase. Those hidden dependencies are real. That 73% co-change rate between billing.py and webhook_handler.py means every time someone changes one without the other, there's a bug. dotscope found it in your git history and will tell every agent about it before they start working.

---

## What happens next

dotscope writes `.scope` files — one per module — that carry the architectural knowledge agents can't derive from code alone. When an agent resolves a scope, it gets the right files, the right context, and the rules it should follow:

```
dotscope check

  HOLD  implicit_contract
    auth/tokens.py modified without api/auth_routes.py (82% co-change)
    Likely needs changes: validate_token(), refresh_handler()

  NOTE  architectural_intent
    New import from payments/ in auth/handler.py
    Intent: decouple auth/ from payments/

dotscope: 1 hold, 1 note — address holds to proceed
```

The hold comes with a fix proposal. The agent applies it without thinking.

If a token budget would silently drop a critical file, dotscope raises a hard error — same as a compiler. No silent corruption.

```
ERROR: Context Exhaustion — budget (4,000) cannot fit required file:
  models/user.py (1,200 tokens)
  Required by assertion: "Auth scope is meaningless without the User model"
```

At the end of the session, dotscope tells you what it prevented:

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

When something goes wrong, `dotscope debug --last` bisects the session to find exactly why — which file was missing, which constraint was ignored, which context section was irrelevant. Four diagnosis categories, zero LLM calls.

Every commit makes it smarter. Every acknowledged exception makes it less noisy. Successful sessions freeze as regression tests so algorithm changes can't silently make things worse.

---

## Setup

```bash
pip install dotscope            # Zero dependencies
dotscope ingest .               # Enter any codebase
dotscope hook install           # Start the feedback loop
```

For agents, add the MCP server:

```json
{
  "mcpServers": {
    "dotscope": { "command": "dotscope-mcp" }
  }
}
```

## CLI

```bash
# Context
dotscope resolve auth --budget 4000
dotscope resolve auth+payments

# Enforcement
dotscope check
dotscope check --backtest
dotscope intent add freeze core/

# Rigor
dotscope test-compiler
dotscope bench
dotscope debug --last

# Maintenance
dotscope health
dotscope impact auth/tokens.py
```

## Docs

- [How It Works](docs/how-it-works.md) — ingest, enforcement, feedback loop, rigor
- [The .scope File](docs/scope-file.md) — fields, assertions, anti-patterns, intent
- [MCP Server Setup](docs/mcp-setup.md) — setup, tools, troubleshooting

## Details

Python 3.9+. Zero dependencies. Cross-platform. 266 tests. `.scope` files are plain YAML. `.dotscope/` is gitignored and rebuildable. [MIT](LICENSE).
