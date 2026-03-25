# dotscope

A self-correcting context engine for AI coding agents.

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

Most tools stop here. dotscope doesn't. After every commit, it observes what the agent actually touched vs. what the scope predicted — and uses the difference to get better. Scopes that start as documentation become intelligence.

## The Loop

```
Agent calls resolve_scope via MCP
  → dotscope logs the prediction (session)
    → Agent works, commits
      → Post-commit hook logs what actually happened (observation)
        → Utility scores update → budget ranking improves
        → Lessons generated → patterns surfaced
        → Invariants enforced → boundaries held
          → Next resolution is more accurate
```

No other tool in the agentic context space closes this loop.

## Usage

```bash
# Enter any codebase
dotscope ingest .                          # AST analysis + git mining + doc absorption → .scope files
dotscope backtest                          # Validate generated scopes against git history

# Resolve
dotscope resolve auth                      # Files the agent should see
dotscope resolve auth --budget 4000        # Best 4K tokens (context first, then files by utility)
dotscope resolve auth+payments             # Union
dotscope resolve auth-tests                # Subtract
dotscope resolve auth@context              # Knowledge only, no files

# Understand
dotscope context auth --section gotchas    # Query specific context sections
dotscope impact auth/tokens.py             # Full transitive blast radius
dotscope virtual                           # Cross-cutting scopes spanning multiple directories

# Monitor
dotscope health                            # Staleness, coverage gaps, import drift
dotscope stats                             # Token savings across all scopes
dotscope utility auth                      # Which files agents actually use
dotscope lessons auth                      # Patterns learned from observations
dotscope invariants auth                   # Boundaries that have never been crossed

# Feedback loop
dotscope hook install                      # Install post-commit observer
dotscope observe <commit>                  # Record what actually happened
dotscope rebuild                           # Regenerate derived state from event logs
```

## MCP Server

Primary interface for agents. Every `resolve_scope` call creates a tracked session.

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
| `impact_analysis("auth/tokens.py")` | Transitive import graph + blast radius |
| `ingest_codebase()` | Reverse-engineer scopes from any repo |
| `backtest_scopes()` | Validate scopes against git history |
| `scope_health()` | Staleness, coverage gaps, drift |
| `scope_observations("auth")` | Recall/precision trends from observation data |
| `scope_lessons("auth")` | Machine-generated lessons from agent behavior |
| `suggest_scope_changes("auth")` | Data-driven includes to add or deprioritize |
| `validate_scopes()` | Check for broken paths |
| `list_scopes()` | All available scopes with descriptions |

## Ingest

`dotscope ingest` enters any codebase by combining four signal sources:

1. **AST analysis** — Python `ast` module for precise imports (relative, star, conditional, TYPE_CHECKING), function signatures, class hierarchies, decorators, public/private detection. Enhanced regex for JS/TS/Go.
2. **Dependency graph** — transitive closure over the import graph. Module boundaries detected by directory cohesion.
3. **Git history** — `--numstat` weighted hotspots, change coupling, implicit contracts, per-file stability classification (stable/volatile/tweaked).
4. **Doc absorption** — README, ARCHITECTURE.md, docstrings, signal comments (INVARIANT, HACK, WARNING). API surfaces extracted from AST.

After synthesis, scopes are **backtested** against git history and **auto-corrected** — files that were consistently needed but missing get added automatically.

## Self-Correction

dotscope tracks its own accuracy. The `.dotscope/` directory (gitignored) stores:

| Directory | Type | Contents |
|-----------|------|----------|
| `sessions/` | Append-only | One JSON per scope resolution (the prediction) |
| `observations/` | Append-only | One JSON per observed commit (the outcome) |
| `utility/` | Derived | Per-file utility scores (touch_count / resolve_count) |
| `lessons/` | Derived + editable | Machine-generated patterns, human-refinable |
| `invariants/` | Derived | Evidence-based boundaries from graph + history |

Sessions and observations are the source of truth. Everything else is rebuilt from them via `dotscope rebuild`.

## Virtual Scopes

Directory scopes capture physical structure. Virtual scopes capture logical architecture — a User lifecycle spanning `models/`, `auth/`, `validators/`, `serializers/`.

Detected automatically from import graph hub analysis: files imported by 3+ files from 2+ directories form a cross-cutting cluster. Filtered by cohesion, named by centrality, deduplicated by overlap.

```bash
dotscope virtual
```

## Scope Algebra

| Operator | Example | Effect |
|----------|---------|--------|
| `+` | `auth+payments` | Union of files, concatenated context |
| `-` | `auth-tests` | Auth files minus test scope |
| `&` | `auth&api` | Intersection |
| `@context` | `auth@context` | Context only |

## Token Budgeting

```bash
dotscope resolve auth --budget 4000 --json
```

Context loads first (always). Then files ranked by historical utility (from observations), task keyword relevance, and size. Explicit includes get a utility floor — core abstractions that are rarely edited but frequently read are never deprioritized into oblivion.

## Lineage

`.gitignore` → what to skip.
`.env` → what to configure.
`Dockerfile` → what to build.
`.scope` → what to understand.

## License

MIT
