# dotscope

Codebase knowledge as a first-class artifact.

```bash
pip install dotscope
```

## What

`.scope` files declare what an agent should understand about a directory — which files matter, which to skip, and the architectural knowledge that isn't in the code.

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

`dotscope ingest .` reverse-engineers these from your dependency graph, git history, and existing docs. Or write them by hand.

## Why

Every agent session starts cold. No memory of why things are the way they are, what's fragile, what's safe to change. `.scope` files are the persistent knowledge layer that compensates for this.

They work for humans too. New developer onboarding? Read the `.scope` files.

## Usage

```bash
dotscope ingest .                          # Generate .scope files from existing codebase
dotscope resolve auth                      # Files the agent should see
dotscope resolve auth --budget 4000        # Best 4K tokens (context loads first, then files by relevance)
dotscope resolve auth+payments             # Union
dotscope resolve auth-tests                # Subtract
dotscope resolve auth@context              # Knowledge only, no files
dotscope context auth --section gotchas    # Query specific context sections
dotscope impact auth/tokens.py             # Blast radius before touching a file
dotscope health                            # Staleness, coverage gaps, import drift
dotscope stats                             # Token savings across all scopes
```

## MCP Server

Primary interface for agents.

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

| Tool | Purpose |
|------|---------|
| `resolve_scope("auth", budget=4000)` | Scoped files + context within token budget |
| `match_scope("fix JWT expiry")` | Task → scope routing |
| `get_context("auth", section="gotchas")` | Architectural knowledge without file loading |
| `impact_analysis("auth/tokens.py")` | Import graph + blast radius |
| `ingest_codebase()` | Reverse-engineer scopes from any repo |
| `scope_health()` | Staleness, coverage gaps, drift |

## Ingest

`dotscope ingest` builds `.scope` files from three signals:

1. **Dependency graph** — import analysis across Python/JS/TS/Go, module boundary detection
2. **Git history** — change coupling, hotspots, co-change patterns
3. **Doc absorption** — README, ARCHITECTURE.md, docstrings, signal comments (`INVARIANT`, `HACK`, `WARNING`)

The `context` field is where the human adds what automation can't: why things are the way they are.

## Scope Algebra

| Operator | Example | Effect |
|----------|---------|--------|
| `+` | `auth+payments` | Union of files, concatenated context |
| `-` | `auth-tests` | Auth files minus test scope |
| `&` | `auth&api` | Intersection |
| `@context` | `auth@context` | Context only |

## `.scopes` Index

Optional repo-root file for task routing:

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
```

## Lineage

`.gitignore` → what to skip.
`.env` → what to configure.
`Dockerfile` → what to build.
`.scope` → what to understand.

## License

MIT
