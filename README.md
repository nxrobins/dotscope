# dotscope

**The context compiler for AI coding agents.**

Drop `.scope` files in your codebase to define what an agent should see, what to skip, and the architectural knowledge that isn't in the code. dotscope resolves these into curated context payloads — the right files, at the right token budget, with the right knowledge.

Or point `dotscope ingest` at any existing codebase and it reverse-engineers scope files from the dependency graph, git history, and existing documentation.

## Install

```bash
pip install dotscope          # CLI only
pip install dotscope[mcp]     # CLI + MCP server
pip install dotscope[all]     # Everything (MCP + accurate token counting)
```

## The Problem

AI agents read your entire codebase when they only need 3 files. This wastes context window on irrelevant code, increases cost, and degrades output — the agent is reasoning over noise.

Every agent session starts cold. No institutional memory. No intuition from months in the codebase. `.scope` files are the persistent engineering brain that compensates for this.

## Quick Start

### 1. Ingest an existing codebase

```bash
dotscope ingest .
```

This analyzes your dependency graph, mines git history for change patterns, absorbs README/docstrings/signal comments, and produces `.scope` files for every detected module. No manual writing needed.

### 2. Or write a `.scope` file manually

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

### 3. Resolve scopes

```bash
dotscope resolve auth                      # File list
dotscope resolve auth --budget 4000        # Best 4K tokens
dotscope resolve auth+payments             # Merge two scopes
dotscope resolve auth-tests                # Subtract test files
dotscope resolve auth@context              # Context only, no files
dotscope resolve auth --json               # JSON output
```

### 4. Query architectural context

```bash
dotscope context auth                      # Full context
dotscope context auth --section gotchas    # Just the gotchas
```

### 5. Check blast radius before coding

```bash
dotscope impact auth/tokens.py
# Imports: models/user.py
# Imported by: api/middleware.py, tests/test_auth.py
# Affected modules: api, tests
# Risk: MEDIUM — 5 files in blast radius
```

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

## CLI Reference

| Command | Description |
|---------|-------------|
| `dotscope ingest [--dir PATH]` | Reverse-engineer .scope files from a codebase |
| `dotscope resolve <expr>` | Resolve scope expression to files |
| `dotscope context <scope>` | Print architectural context |
| `dotscope match "<task>"` | Match task to scope(s) |
| `dotscope impact <file>` | Blast radius prediction |
| `dotscope init [--scan]` | Create .scope file |
| `dotscope validate` | Check .scope files for broken paths |
| `dotscope stats` | Token savings report |
| `dotscope tree` | Visual scope tree |
| `dotscope health` | Staleness, coverage, drift detection |

## Scope Composition

Combine scopes with operators:

| Operator | Example | Effect |
|----------|---------|--------|
| `+` | `auth+payments` | Union of files, concatenated context |
| `-` | `auth-tests` | Auth files minus test scope files |
| `&` | `auth&api` | Only files in both scopes |
| `@context` | `auth@context` | Context only, no files |

## Token Budgeting

Request a budget instead of dumping all files:

```bash
dotscope resolve auth --budget 4000 --json
```

The resolver includes context first (architectural knowledge), then ranks files by relevance and loads them until the budget is hit. Reports what was truncated.

## Structured Context

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

Query specific sections: `dotscope context payments --section gotchas`

## Ingest Pipeline

`dotscope ingest` enters any codebase by combining three signal sources:

1. **Dependency graph** — parses imports across Python/JS/TS/Go, detects module boundaries via directory cohesion
2. **Git history** — mines change coupling (files that always change together), hotspots (high churn), implicit contracts (co-change patterns)
3. **Doc absorption** — scans README, ARCHITECTURE.md, docstrings, and signal comments (WARNING, HACK, INVARIANT, NOTE)

## Health Monitoring

```bash
dotscope health
```

Detects:
- **Staleness** — files modified since .scope was last updated
- **Coverage gaps** — directories with source files but no .scope
- **Import drift** — imports in scoped files not reflected in includes

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

## License

MIT
