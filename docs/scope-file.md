# The .scope File

A `.scope` file declares what an agent should understand about a directory in your codebase. dotscope generates these during ingest. You can edit them by hand.

## Location

Each `.scope` file lives in the directory it describes:

```
myproject/
  auth/.scope
  api/.scope
  payments/.scope
  .scopes            # index file at project root
```

## Full Example

```yaml
description: Authentication and session management
includes:
  - auth/handler.py
  - auth/tokens.py
  - auth/middleware.py
  - auth/oauth.py
  - models/user.py
excludes:
  - auth/tests/
  - auth/fixtures/
context: |
  ## Implicit Contracts (from git history)
  - auth/handler.py and cache/sessions.py change together 68% of the time
  - auth/tokens.py changes usually require a corresponding change to api/auth_routes.py

  ## Stability
  - handler.py: stable (12 commits, 340 lines)
  - tokens.py: volatile (47 commits, 1,200 lines)
  - oauth.py: stable (3 commits, 80 lines)

  ## Architecture
  JWT tokens with 15-min access / 7-day refresh rotation.
  Session store is Redis. User model has soft deletes —
  never call .delete(), use .deactivate().

  ## Gotchas
  OAuth provider config is fragile. Check auth/README.md first.
  Token refresh endpoint has rate limiting at the nginx layer,
  not in application code.
related:
  - payments/.scope
  - api/.scope
tokens_estimate: 1420
confidence: 0.87
signals:
  - "history: 3 implicit contracts"
  - "docs: absorbed 4 fragments"
  - "graph: 2 external deps, depended on by 3 modules"
```

## Fields

### `description`

One-line summary of what this module does. Generated from absorbed docs and directory structure. Editable.

### `includes`

Files the agent should see when resolving this scope. Generated from the dependency graph: files in this directory plus cross-module dependencies (files outside the directory that this module imports or that import from it).

When a token budget is applied, dotscope ranks these by utility score and returns the highest-value subset.

### `excludes`

Files to skip. Typically test fixtures, generated files, and vendored code. Generated from common patterns. Editable.

### `context`

The most important field. Carries knowledge that doesn't exist anywhere in the code: architectural decisions, implicit contracts, stability information, gotchas, and operational context.

dotscope populates this from multiple sources, in priority order:

1. **Implicit contracts** — file pairs with high co-change rates from git history
2. **Stability profiles** — per-file volatility classification from commit frequency
3. **Absorbed documentation** — READMEs, docstrings, signal comments
4. **Dependency information** — what this module imports, what depends on it
5. **Recent changes** — last few commit messages touching this module
6. **Transitive dependencies** — downstream impact information

You can edit context freely. Hand-authored content is preserved across re-ingests as long as dotscope can identify it (content not under a `## ` header that dotscope generates).

Context is where dotscope's value compounds. The agent reads it before working. Attribution hints extract the highest-value lines and tag their provenance so the agent can say "based on git history analysis..." vs "the scope notes that..."

### `related`

Other scopes that are frequently relevant alongside this one. Generated from import relationships and co-change patterns. The agent can use these to proactively pull in related context.

### `tokens_estimate`

Approximate token count for this scope's includes + context. Used for budget calculations. Recomputed on ingest.

### `confidence`

How confident dotscope is in this scope's quality, from 0 to 1. Based on backtest recall, observation history, and signal coverage. Scopes with low confidence benefit most from manual editing.

### `signals`

Metadata about what sources contributed to this scope. Diagnostic information, not consumed by agents.

## Editing by Hand

`.scope` files are plain YAML. Edit anything. The most common edits:

**Add a gotcha to context.** If you know something about this module that isn't in the code or docs, add it to the context field. This is the highest-leverage edit you can make — it gives the agent knowledge it literally cannot derive on its own.

**Adjust includes.** If the agent consistently needs a file that isn't in the includes list, add it. If a file is included but never relevant, remove it. The feedback loop will eventually correct this, but manual adjustment is faster.

**Add excludes.** Large generated files, vendored dependencies, and test fixtures that inflate token counts without adding value.

## Signal Comments

You can add special comments in your source code that dotscope will absorb into the nearest scope's context during ingest:

```python
# SCOPE: JWT tokens use 15-min access / 7-day refresh rotation
# CONTEXT: Session store is Redis, not the database
# GOTCHA: OAuth provider config is fragile
```

Prefix a comment with `SCOPE:`, `CONTEXT:`, or `GOTCHA:` and dotscope will extract it. This lets you embed agent-readable knowledge directly in the code where it's most relevant.

## The .scopes Index

The `.scopes` file at the project root is an index of all scopes:

```yaml
version: 1
total_repo_tokens: 47000
scopes:
  - path: auth/.scope
    directory: auth
    description: Authentication and session management
  - path: api/.scope
    directory: api
    description: REST API routes and middleware
  - path: payments/.scope
    directory: payments
    description: Payment processing and billing
```

The MCP server reads this on startup. You shouldn't need to edit it directly — `dotscope ingest` regenerates it.

## Re-ingesting

Running `dotscope ingest .` again regenerates all scopes. Scopes that have been manually edited will have their generated sections updated while preserving hand-authored content in the context field.

To regenerate a single module: `dotscope ingest auth/`.

To see what would change without writing anything: `dotscope ingest . --dry-run`.
