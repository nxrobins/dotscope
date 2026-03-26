<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

Point it at any codebase. It reads your dependency graph, mines your git history, and tells you things about your own code you didn't know.

```bash
pip install dotscope
dotscope ingest .
```

```
dotscope: building dependency graph...         247 files, 1832 edges, 12 modules
dotscope: mining git history (500 commits)...  340 commits, 4 contracts (2.1s)
dotscope: absorbing documentation...           23 fragments
dotscope: discovering conventions...           3 patterns
dotscope: discovering voice...                 adaptive mode
dotscope: generating scopes...                 12 scopes, 2 virtual
dotscope: backtesting (50 commits)...          91% recall (1.4s)

⚡ Discoveries

  Hidden dependencies (from 200 commits):
    billing.py → webhook_handler.py    73% co-change, undocumented
    auth/handler.py → cache/sessions.py  68% co-change, undocumented

  Cross-cutting hub:
    models/user.py imported by 14 files across 5 modules
    A change here affects 23 files transitively

  Conventions discovered:
    "Route Handler" — 8 files in api/routes/
      All decorated with @router or @app.route
      None import sqlalchemy or psycopg2
    "Repository" — 4 files ending in _repo.py
      All implement get() and save()

📊 Backtested against 200 recent commits:
  Overall recall: 91% — scopes would have given agents the right files
  Token reduction: 88% — from ~47,000 to ~4,200 per resolution

  auth/    ████████░░ 93%
  api/     █████████░ 96%
  payments ███████░░░ 71% ← needs attention
```

Those hidden dependencies are from your git history. That 73% co-change rate between billing.py and webhook_handler.py means a change to one without the other is likely a bug. The conventions are structural patterns your team follows but never documented. Every agent gets all of it before writing a line.

---

## What happens next

dotscope writes `.scope` files — one per module — that carry the architectural knowledge agents can't derive from code alone. When an agent resolves a scope, it gets the right files, the right context, and the rules it should follow:

```
dotscope check

  HOLD  implicit_contract
    auth/tokens.py modified without api/auth_routes.py (82% co-change)
    Likely needs changes: validate_token(), refresh_handler()

  HOLD  convention_drift
    Agent added SQL logic to api/routes/users.py
    This file is recognized as a 'Route Handler' (100% compliance)
    Rule violation: Route Handlers cannot import sqlalchemy
    → Move this logic to a 'Repository' class

  NOTE  architectural_intent
    New import from payments/ in auth/handler.py
    Intent: decouple auth/ from payments/

dotscope: 2 holds, 1 note — address holds to proceed
```

Holds come with fix proposals. The pre-commit hook blocks the commit until they're addressed. The agent sees the error, fixes the code, and tries again.

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

The pre-commit git hook is the enforcement guarantee. It works everywhere git runs: Claude Desktop, Claude Code, VS Code, terminal. No opt-in, no tool calls, no agent cooperation required. The agent runs `git commit`, the hook runs `dotscope check`, HOLDs block the commit. The agent gets the error and fixes the code.

---

## Setup

```bash
pip install dotscope            # Zero dependencies
dotscope ingest .               # Enter any codebase
dotscope hook install           # Enforce rules + start the feedback loop
```

The pre-commit hook blocks commits that violate architectural rules. The post-commit hook records observations so scopes improve over time. Both install with one command.

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

# Conventions
dotscope conventions                  # List all conventions + compliance
dotscope conventions --discover       # Discover patterns from codebase
dotscope diff --staged                # Semantic diff against conventions

# Voice
dotscope voice                        # Show discovered voice config
dotscope voice --upgrade typing       # Tighten enforcement as codebase improves

# Rigor
dotscope test-compiler
dotscope bench
dotscope debug --last

# Hooks
dotscope hook install             # Pre-commit enforcement + post-commit feedback
dotscope hook claude              # Claude Code pre-commit hook (defense-in-depth)
dotscope hook status              # Check what's installed

# Maintenance
dotscope health
dotscope impact auth/tokens.py
```

## Docs

- [How It Works](docs/how-it-works.md) — ingest, enforcement, feedback loop, rigor
- [The .scope File](docs/scope-file.md) — fields, assertions, anti-patterns, intent
- [MCP Server Setup](docs/mcp-setup.md) — setup, tools, troubleshooting

## Architecture

```
dotscope/
├── models/              # What the compiler knows
│   ├── core.py          #   Static structure (AST, graph, scopes, conventions)
│   ├── history.py       #   Empirical behavior (contracts, stability)
│   ├── intent.py        #   Human rules (intents, conventions, assertions, checks)
│   ├── state.py         #   Persistent memory (sessions, observations)
│   └── passes.py        #   Transient outputs (ingest plans, semantic diffs)
├── passes/              # What the compiler does
│   ├── graph_builder.py #   Dependency analysis
│   ├── history_miner.py #   Git history mining
│   ├── budget_allocator.py    # Token budgeting with assertions
│   ├── convention_discovery.py # Discover conventions from structural patterns
│   ├── convention_parser.py   # Match files to conventions, check rules
│   ├── convention_compliance.py # Compliance tracking + severity
│   ├── semantic_diff.py       # Convention-level structural diff
│   ├── voice_discovery.py     # Scan codebase for coding style patterns
│   ├── voice_defaults.py      # Prescriptive defaults for new codebases
│   ├── voice.py               # Voice injection into resolve responses
│   ├── lazy.py                # On-demand single-module ingest
│   ├── incremental.py         # Post-commit incremental scope updates
│   └── sentinel/        #   Enforcement engine (8 checks, constraints, decay)
├── storage/             # How the compiler remembers
│   ├── session_manager.py     # Session + observation persistence
│   ├── cache.py               # Cached analysis data
│   ├── git_hooks.py           # Pre-commit enforcement + post-commit feedback
│   ├── claude_hooks.py        # Claude Code PreToolUse hook
│   ├── onboarding.py          # Stage-aware milestone tracking
│   ├── timing.py              # Operation instrumentation
│   ├── near_miss.py           # Near-miss detection persistence
│   └── incremental_state.py   # Continuous ingest drift tracking
├── progress.py          # Streaming progress emitter
├── cli.py               # Human interface
└── mcp_server.py        # Agent interface
```

The Nouns live in `models/`. The Verbs live in `passes/`. The Memory lives in `storage/`. The Interfaces are at the root.

## Details

Python 3.9+. Zero dependencies. Cross-platform. 314 tests. `.scope` files are plain YAML. `.dotscope/` is gitignored and rebuildable. [MIT](LICENSE).
