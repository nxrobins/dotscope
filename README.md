# dotscope

**Codebase knowledge as a first-class engineering artifact.**

`.gitignore` made version control a discipline. `Dockerfile` made environments a discipline. `.scope` makes codebase knowledge a discipline — readable by humans, actionable by agents.

Every codebase has knowledge that isn't in the code: why the auth module uses soft deletes, why you never call that API directly, which abstractions are load-bearing and which are legacy. This knowledge lives in senior developers' heads. When they leave, it leaves. When an AI agent enters the codebase, it starts at zero.

dotscope captures that knowledge. Drop `.scope` files in your repo, or run `dotscope ingest` to reverse-engineer them from your dependency graph, git history, and existing documentation. Agents read the `.scope` file before they read a single line of code — and they know what matters.

## Install

```bash
pip install dotscope          # CLI only
pip install dotscope[mcp]     # CLI + MCP server
pip install dotscope[all]     # Everything (MCP + accurate token counting)
```

## 30 Seconds to Scoped

```bash
# Point at any codebase — dotscope reverse-engineers scope files automatically
dotscope ingest .

# See what the agent would see
dotscope resolve auth

# See what the agent would know
dotscope context auth

# See what breaks if you touch a file
dotscope impact auth/tokens.py
```

That's it. Your agent now has architectural intuition.

## What a `.scope` File Looks Like

```yaml
# auth/.scope
description: Authentication and session management
includes:
  - auth/
  - models/user.py
excludes:
  - auth/tests/fixtures/
context: |
  Auth uses JWT tokens with 15-min access / 7-day refresh rotation.
  Session store is Redis (config/redis.py).

  ## Invariants
  Never call .delete() on User — use .deactivate().

  ## Gotchas
  OAuth provider config is fragile — check auth/README.md first.
related:
  - payments/.scope
  - api/.scope
tags:
  - security
  - session-management
```

Three things `.gitignore` isn't: it carries **knowledge** (the `context` field), it's **additive** (what to focus on, not what to skip), and it **cross-references** (related scopes for tasks that span boundaries).

## Why This Exists

AI coding agents waste 60-80% of their context window on irrelevant code. But the real problem isn't token waste — it's that agents have **zero institutional memory**. No intuition. No sense of what's fragile. No knowledge of decisions made six months ago that constrain what's possible today.

`.scope` files are externalized engineering intuition. They turn the invisible architecture visible. And they work for humans too — a new developer onboarding reads the `.scope` files and gets the same institutional knowledge the agent gets.

## MCP Server

The MCP server is the primary interface — agents call it directly.

```bash
dotscope-mcp    # Starts stdio transport
```

Configure in Claude Desktop / any MCP client:

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "dotscope-mcp"
    }
  }
}
```

**Tools exposed:**

| Tool | What it does |
|------|-------------|
| `resolve_scope("auth", budget=4000)` | Curated file list + context within token budget |
| `match_scope("fix JWT expiry")` | Find the right scope for a task |
| `get_context("auth", section="gotchas")` | Architectural knowledge without loading files |
| `list_scopes()` | All available scopes with descriptions |
| `ingest_codebase()` | Reverse-engineer scopes from any repo |
| `impact_analysis("auth/tokens.py")` | Blast radius prediction |
| `validate_scopes()` | Check for broken paths and issues |
| `scope_health()` | Staleness, coverage gaps, import drift |

## Scope Resolution

```bash
dotscope resolve auth                      # File list
dotscope resolve auth --budget 4000        # Best 4K tokens
dotscope resolve auth+payments             # Merge two scopes
dotscope resolve auth-tests                # Subtract test files
dotscope resolve auth@context              # Context only, no files
dotscope resolve auth --json               # JSON output
```

### Scope Algebra

Combine scopes with operators:

| Operator | Example | Effect |
|----------|---------|--------|
| `+` | `auth+payments` | Union of files, concatenated context |
| `-` | `auth-tests` | Auth files minus test scope files |
| `&` | `auth&api` | Only files in both scopes |
| `@context` | `auth@context` | Context only, no files |

### Token Budgeting

```bash
dotscope resolve auth --budget 4000 --json
```

Context loads first (architectural knowledge). Then files rank by relevance until the budget is hit. You always get the knowledge; you get as much code as fits.

## Architectural Context

```bash
dotscope context auth                      # Full context
dotscope context auth --section gotchas    # Just the gotchas
```

Use `## Section` headers in context blocks to create queryable sections:

```yaml
context: |
  ## Invariants
  All amounts in cents. Never use floats for money.

  ## Gotchas
  Stripe webhooks are idempotent but our handler isn't.

  ## Conventions
  New endpoints go through the rate limiter middleware.
```

## Impact Analysis

```bash
dotscope impact auth/tokens.py
# Imports: models/user.py
# Imported by: api/middleware.py, tests/test_auth.py
# Affected modules: api, tests
# Risk: MEDIUM — 5 files in blast radius
```

Before an agent touches a file, it knows the blast radius. Before a human reviews a PR, they know what else might break.

## Ingest Pipeline

`dotscope ingest` enters any codebase — no manual `.scope` writing needed. Three signal sources:

1. **Dependency graph** — parses imports across Python/JS/TS/Go, detects module boundaries via directory cohesion
2. **Git history** — mines change coupling (files that always change together), hotspots (high churn), implicit contracts (co-change patterns)
3. **Doc absorption** — scans README, ARCHITECTURE.md, docstrings, and signal comments (`WARNING`, `HACK`, `INVARIANT`, `NOTE`)

The human then edits the `context` field — that's the part that can't be automated. Everything else is scaffolding.

## Health Monitoring

```bash
dotscope health
```

Detects:
- **Staleness** — files modified since `.scope` was last updated
- **Coverage gaps** — directories with source files but no `.scope`
- **Import drift** — imports in scoped files not reflected in includes

Scope files that drift from reality are worse than no scope files. `dotscope health` keeps them honest.

## CLI Reference

| Command | Description |
|---------|-------------|
| `dotscope ingest [--dir PATH]` | Reverse-engineer `.scope` files from a codebase |
| `dotscope resolve <expr>` | Resolve scope expression to files |
| `dotscope context <scope>` | Print architectural context |
| `dotscope match "<task>"` | Match task to scope(s) |
| `dotscope impact <file>` | Blast radius prediction |
| `dotscope init [--scan]` | Create `.scope` file |
| `dotscope validate` | Check `.scope` files for broken paths |
| `dotscope stats` | Token savings report |
| `dotscope tree` | Visual scope tree |
| `dotscope health` | Staleness, coverage, drift detection |

## `.scopes` Index

Optional repo-root file for fast task routing:

```yaml
version: 1
scopes:
  auth:
    path: auth/.scope
    keywords: [authentication, login, JWT, session, OAuth]
  payments:
    path: payments/.scope
    keywords: [billing, stripe, invoice, subscription]
defaults:
  max_tokens: 8000
  include_related: false
```

## The Lineage

`.gitignore` told version control what to skip.
`.env` told applications what to configure.
`Dockerfile` told infrastructure what to build.
`AGENTS.md` told AI agents how to behave.
`.scope` tells AI agents what to understand.

Each one made an invisible engineering concern into a first-class artifact. Each one created a new discipline. dotscope is the first primitive of agentic engineering.

## License

MIT
