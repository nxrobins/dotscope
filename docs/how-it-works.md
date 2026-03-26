# How It Works

dotscope builds `.scope` files by analyzing your dependency graph, git history, and existing docs. It validates them against your commit history. Then it watches what agents actually do, learns from every commit, enforces your codebase's rules, and tells you what it prevented.

## The Ingest Pipeline

`dotscope ingest .` runs seven steps:

**1. Dependency graph.** Static analysis of imports across all files. Produces a directed graph: module boundaries, cross-cutting hubs (files imported by many modules), and transitive blast radius for any file. Python uses AST parsing; JS/TS/Go use enhanced regex.

**2. History mining.** Analyzes your git log (up to 500 commits) for patterns invisible in the code: implicit contracts (files that always change together), stability profiles, churn hotspots, and function-level co-change data.

**3. Document absorption.** Reads READMEs, docstrings, and signal comments (`SCOPE:`, `CONTEXT:`, `GOTCHA:` markers). Extracts knowledge a human wrote but an agent would never see.

**4. Scope generation.** For each module, synthesizes a `.scope` file. Includes come from the dependency graph. Context is assembled from implicit contracts, stability profiles, absorbed docs, dependency info, and recent changes — in that priority order.

**5. Convention discovery.** Analyzes structural patterns across files to find architectural conventions the team follows but never documented. Three clustering passes: shared decorators (strongest signal), shared base classes, shared naming suffixes. For each cluster, derives match criteria and rules (required methods, prohibited imports). Discovered conventions are written to `intent.yaml`.

**6. Voice discovery.** Scans every file for coding style signals: type hint adoption rate, docstring style, error handling patterns, structural preferences (early returns vs nested), comprehension density. On new codebases (<10 files or <20 commits), writes prescriptive defaults. On existing codebases, codifies what's already there. Voice config is written to the `voice:` block in `intent.yaml`.

**7. Backtest validation.** Replays recent commits: would the scope have pointed the agent at the right files? Reports recall per scope and token reduction. Auto-corrects low-scoring scopes and reruns.

Each step prints a status line to stderr as it runs. `--quiet` suppresses progress for CI.

After ingest, structured data is cached in `.dotscope/` (history, graph hubs, invariants) so the MCP server can use it at runtime without re-computing. Incremental state is reset so the post-commit hook can track drift from this baseline.

### Lazy Resolve

If an agent resolves a module that hasn't been ingested, dotscope ingests just that module on demand instead of returning an error.

```
Agent calls: resolve_scope("billing")

dotscope: billing/ not yet scoped — generating on demand (1.8s)

{ "scope": "billing/", "files": [...], ... }
```

Lazy ingest builds a partial graph (module files + one level of imports), mines 50 recent commits filtered to the module path, and synthesizes one scope. 2-3 seconds instead of 30. A `.dotscope/needs_full_ingest` marker is written so the next full ingest fills in transitive dependencies and cross-module contracts.

### Continuous Ingest

The post-commit hook incrementally updates scopes on every commit. The pre-commit hook enforces rules before every commit. No manual re-ingest needed for routine changes.

What updates per commit:

| Data | Method |
|------|--------|
| Scope includes | New file in module dir added, deleted file removed |
| File stabilities | Commit count incremented, volatility reclassified |
| Co-change matrix | Pairs in this commit tracked |

What does NOT update per commit (requires full ingest): dependency graph, transitive dependencies, convention discovery.

After 200 commits without a full re-ingest, dotscope surfaces a health warning.

## Scope Resolution

When an agent calls `resolve_scope`:

1. Parse the scope expression (algebra: `auth+payments`, `auth-tests`, `auth&api`, `auth@context`)
2. Load the `.scope` file(s)
3. Inject lessons and invariants from the observation store into context
4. Apply token budget (files ranked by historical utility, then keyword relevance, then size)
5. Build filtered constraints (contracts, anti-patterns, boundaries, intents, convention blueprints — relevant to this scope)
6. Return files, context, constraints, attribution hints, accuracy, health warnings, near-misses

## Routing, Not Enforcement

dotscope's architecture is a bowling alley with the bumpers up, not a maze of laser tripwires. The agent codes as fast and creatively as it wants. dotscope nudges files into the correct semantic buckets. Rules exist to make the agent faster, not slower.

Three points of contact:

**Routing (at resolve time).** Every `resolve_scope` response includes `constraints` (what not to do) and `routing` (what to do). Convention blueprints, voice rules, implicit contracts — the agent knows the patterns before writing code. This is the primary mechanism. If the routing is good, the checks almost never fire.

**Verification (before commit).** `dotscope_check` returns GUARDs (must address), NUDGEs (course corrections), and NOTEs (informational). Only GUARDs block. NUDGEs are guidance the agent sees and self-corrects on.

**Gate (at commit time).** The pre-commit hook runs `dotscope check`. Only GUARDs block the commit. NUDGEs and NOTEs print to stderr and pass through.

Three severity levels:

| Severity | Commits | Purpose |
|----------|---------|---------|
| **GUARD** | Blocks | Protective wall. Frozen modules, deprecated imports. |
| **NUDGE** | Passes | Course correction. Contracts, conventions, anti-patterns. |
| **NOTE** | Passes | Informational. Direction reversals, stability. |

Eight check categories:

| Category | Severity | What it catches |
|----------|----------|-----------------|
| Intent: freeze | GUARD | Change to a frozen module |
| Intent: deprecate | GUARD | New usage of deprecated code |
| Boundary violation | NUDGE | Agent modified files outside its resolved scope |
| Implicit contract | NUDGE | Coupled file modified without its pair |
| Anti-pattern | NUDGE | Prohibited pattern in added lines |
| Convention violation | NUDGE or NOTE | File drifting from its convention's rules |
| Voice violation | NUDGE or NOTE | Bare except or missing type hint |
| Dependency direction | NOTE | New import reversing established flow |
| Stability concern | NOTE | Large change to a stable file |

## Architectural Intent

`intent.yaml` at the project root declares where the codebase is headed:

```yaml
intents:
  - directive: decouple
    modules: [auth/, payments/]
    reason: "Auth should not depend on payment internals"
  - directive: freeze
    modules: [core/]
    reason: "Stable module. Changes require acknowledgment."
  - directive: deprecate
    files: [utils/legacy.py]
    replacement: utils/helpers.py
```

Four directives: `decouple` (new coupling is NOTE), `deprecate` (new usage is HOLD), `freeze` (any change is HOLD), `consolidate` (moving away from target is NOTE).

Intents flow through constraints (at resolve), checks (before commit), and the session summary (counterfactuals when respected).

## Conventions

Conventions are structural patterns your team follows but never writes down. dotscope discovers them during ingest by clustering files that share decorators, base classes, or naming patterns.

```
dotscope conventions --discover

⚡ Discovered conventions:

  "Route Handler" — 8 files in api/routes/
    All decorated with @router or @app.route
    Prohibited imports: sqlalchemy, psycopg2
    Compliance: 100%

  "Repository" — 4 files ending in _repo.py
    Required methods: get, save
    Compliance: 85%
```

Discovered conventions are written to `intent.yaml` alongside intents:

```yaml
conventions:
  - name: "Route Handler"
    source: discovered
    match:
      any_of:
        - has_decorator: "app\\.route|router"
    rules:
      prohibited_imports: [sqlalchemy, psycopg2]
    description: "Handles HTTP requests and delegates to Services."
    compliance: 1.0
```

### How they work

**Discovery.** Three clustering passes during ingest: shared decorators (strongest signal — survives refactors), shared base classes, shared naming suffixes. For each cluster of 3+ files, dotscope derives match criteria (what makes a file belong) and rules (what it must/must not do).

**Matching.** `any_of` / `all_of` logic. Structural signals (decorators, base classes, imports) take priority over path patterns. A file matching structural criteria but not path still matches. A file matching path but not structural criteria doesn't.

**Enforcement.** Convention rules are checked by `dotscope check` like any other check. Severity scales with compliance: >=80% compliance = HOLD, 50-79% = NOTE, <50% = retired (no longer enforced).

**Blueprint injection.** When an agent resolves a scope containing files that match a convention, the convention's rules are injected as constraints. The agent builds the class correctly on the first try.

**Compliance tracking.** During ingest, dotscope computes what percentage of matching files follow each convention's rules. Declining compliance triggers a health warning.

### Semantic diff

`dotscope diff --staged` translates a git diff into convention-level structural changes:

```
Semantic Diff:
  [ADDED]    Route Handler: api/routes/billing.py
  [ADDED]    Repository: models/billing_repo.py
  [MODIFIED] Dependency: 'Route Handler' now depends on 'Repository'

  Conventions: All upheld
```

## Acknowledge Flow

Sometimes breaking a rule is correct:

```bash
dotscope check --acknowledge contract_auth_tokens_api_a1b2c3
```

Acknowledgments are recorded. 3+ acknowledgments of the same constraint within 30 days decay its confidence by 0.1 per excess. Below 0.5, the constraint becomes a NOTE instead of HOLD. Floor at 0.3 — core rules survive.

## Voice

Voice is how the codebase writes code. Type hint density, docstring style, error handling patterns, structural preferences. dotscope discovers it during ingest and teaches agents to match it.

Two modes: **prescriptive** (new codebases, <10 files or <20 commits) provides opinionated defaults. **Adaptive** (existing codebases) scans every function, docstring, and exception handler, then codifies what the codebase already does.

Override with `dotscope ingest . --voice prescriptive` or `--voice adaptive`.

Voice config is written to the `voice:` block in `intent.yaml`. Two rules get mechanical AST checking via `dotscope check`:

- **Bare excepts**: severity derived from codebase rate. <10% bare = HOLD, 10-30% = NOTE, >30% = not enforced.
- **Missing type hints**: only fires on new or modified functions. Existing untyped functions are grandfathered. >80% adoption = NOTE, otherwise not enforced.

`dotscope voice --upgrade typing` tightens enforcement as the codebase improves.

## The Feedback Loop

**Prediction.** Every `resolve_scope` call is logged with the files served and constraints applied.

**Observation.** After the agent commits, the post-commit hook compares what was touched against what was predicted. Produces accuracy scores and identifies gaps.

**Learning.** Observations update utility scores per file. High-utility files rank higher in budget allocation. Lessons are generated from patterns. Invariants are detected from graph + history.

**Correction.** Scopes improve automatically. The post-commit delta shows it happening:

```
dotscope: observation recorded for auth/
  auth/ predicted 7/8 files correctly (88%)
  Missing: tokens.py
  Utility scores updated
```

## Counterfactual Session Summary

At session end, dotscope shows what it prevented — not just what it served:

```
── dotscope session ──────────────────────────────
  3 scopes resolved · 4,200 tokens served (91% reduction)

  What dotscope prevented:
    Agent used .deactivate() instead of .delete() on User
      ← auth/ scope context
    Agent included webhook_handler.py alongside billing.py
      ← implicit contract (73% co-change)

  What dotscope provided:
    4 attribution hints served
    3 constraints applied
───────────────────────────────────────────────────
```

Three counterfactual types: anti-patterns avoided, contracts honored, intents respected. Only surfaces when the constraint was actually served to the agent. Gated by 3+ observations.

## Onboarding

dotscope tracks milestones in `.dotscope/onboarding.json` and prints one next step at a time:

| After | Prompt |
|-------|--------|
| First ingest | `dotscope check --backtest` |
| First backtest | `dotscope conventions` |
| Conventions reviewed | `dotscope voice` |
| Voice reviewed | Add dotscope to your agent |
| First MCP session | `dotscope hook install` |
| Hook installed | Stop prompting |

Complexity is gated: counterfactuals appear after 3+ observations, health nudges after 7+ days. Each prompt appears once.

## Compiler Rigor

dotscope treats context resolution like compilation. Four features prevent silent corruption:

### Architectural Assertions

Critical files and context can be declared non-negotiable:

```yaml
# In intent.yaml (project-wide)
assertions:
  - scope: auth/
    ensure_includes: [models/user.py]
    reason: "Auth scope is meaningless without the User model"

# In .scope files (per-scope)
assertions:
  ensure_includes: [models/user.py]
  ensure_context_contains: ["soft deletes"]
```

Asserted files get infinite utility in the budgeting algorithm — they're selected first, unconditionally. If the budget can't fit them, dotscope raises a `ContextExhaustionError` instead of silently dropping critical context. Same as a compiler error.

Three types: `ensure_includes` (files must be present), `ensure_context_contains` (substrings in context), `ensure_constraints` (constraints field must be populated).

### Observation Regression Suite

Successful agent sessions (recall ≥ 80%) are automatically frozen as test cases in `.dotscope/regressions/`. When dotscope's algorithms change, replay them:

```bash
dotscope test-compiler

  regression_a1b2c3  auth (budget 4000)
    Files: 3/3 same  OK

  regression_j0k1l2  api (budget 3000)
    REGRESSION: models/request.py no longer resolved

  46/47 passed · 1 regression detected
```

If a file that previously led to a successful commit is no longer resolved under the same conditions, that's a regression.

### Benchmarking

```bash
dotscope bench

  Token Efficiency
    Efficiency ratio: 73.8%

  Hold Rate
    Effective hold rate: 10.6%

  Compilation Speed
    Median resolve: 12ms, P95: 34ms

  Scope Health
    Scopes with >80% recall: 9/12
```

Four metrics from stored data: token efficiency (served vs used), hold rate (catches minus false positives), compilation speed (instrumented timing), scope health (recall + staleness).

### Context Bisection

When an agent writes bad code, `dotscope debug` finds out why — deterministically, with zero LLM calls:

```bash
dotscope debug --last

  File Bisection
    Files that mattered: auth/handler.py, models/user.py
    Missing files: cache/sessions.py

  Constraints Violated
    auth/handler.py ↔ cache/sessions.py (73% co-change)

  Diagnosis: resolution_gap
    -> Add cache/sessions.py to scope includes
    -> Consider increasing budget from 4000 to 6000
```

Four diagnosis categories: resolution gap (dotscope didn't serve something needed), constraint gap (a rule should have existed), agent ignored context (right info served, agent didn't use it), context conflict (contradictory guidance).

## Architecture

dotscope is structured as an agentic compiler. The codebase separates data definitions (the Nouns), analysis operations (the Verbs), and persistence (the Memory).

### models/ — What the compiler knows

Five domain files, each owning a distinct category of data:

- **core.py** — Static architecture: `ScopeConfig`, `FileAnalysis`, `DependencyGraph`, `FileNode`, `ResolvedImport`. What the codebase *is* right now.
- **history.py** — Empirical behavior: `ImplicitContract`, `FileHistory`, `ChangeCoupling`, `HistoryAnalysis`. How the codebase behaves over time.
- **intent.py** — Human rulebook: `IntentDirective`, `ConventionRule`, `DiscoveredVoice`, `Assertion`, `CheckResult`, `ProposedFix`, `Severity`. How the codebase *must* be treated.
- **state.py** — Persistent memory: `SessionLog`, `ObservationLog`, `BenchReport`, `RegressionCase`, `BisectionResult`. The schemas for `.dotscope/` event logs.
- **passes.py** — Transient outputs: `IngestPlan`, `PlannedScope`, `VirtualScope`, `SemanticDiffReport`. Data transfer objects that live only during a single operation.

No model file imports from any functional module. Data definitions are the foundation everything else builds on.

### passes/ — What the compiler does

Analysis and enforcement operations that produce or consume models:

- **ast_analyzer.py** — Populates `models.core` with structural analysis from Python AST
- **graph_builder.py** — Builds `DependencyGraph` from import analysis
- **history_miner.py** — Mines git log to produce `HistoryAnalysis`
- **budget_allocator.py** — Applies token budgets with assertion enforcement
- **backtest.py** — Replays commits against scopes to measure recall
- **virtual.py** — Detects cross-cutting scopes from graph hub analysis
- **convention_discovery.py** — Multi-pass clustering to discover structural conventions
- **convention_parser.py** — Matches files to conventions, checks rules
- **convention_compliance.py** — Compliance tracking and severity thresholds
- **semantic_diff.py** — Translates git diff into convention-level structural changes
- **voice_discovery.py** — Scans every function, docstring, exception handler for coding style signals
- **voice_defaults.py** — Prescriptive voice config for new codebases
- **voice.py** — Voice injection into resolve responses, canonical snippet extraction
- **sentinel/** — The enforcement engine. Runs 8 checks (boundary, contracts, anti-pattern, convention, voice, direction, stability, intent), builds constraints for prophylactic injection, manages acknowledgment decay.

### storage/ — How the compiler remembers

Infrastructure that reads and writes `models.state` to disk:

- **session_manager.py** — Creates sessions, records observations, manages `.dotscope/sessions/` and `.dotscope/observations/`
- **cache.py** — Caches analysis data (history, graph hubs) for MCP server startup
- **git_hooks.py** — Pre-commit enforcement + post-commit feedback hooks
- **claude_hooks.py** — Claude Code PreToolUse hook installation
- **onboarding.py** — Stage-aware milestone tracking
- **timing.py** — Operation instrumentation for benchmarking
- **near_miss.py** — Near-miss detection persistence

### Root level — The interfaces

The root `dotscope/` directory contains only entry points and orchestrators:

- **cli.py** — Human terminal interface (all CLI commands)
- **mcp_server.py** — Agent protocol interface (all MCP tools)
- **composer.py** — Scope algebra orchestrator (union, subtract, intersect)
- **resolver.py** — File resolution orchestrator
- **intent.py** — CLI logic for managing `intent.yaml`

## What's in `.dotscope/`

Runtime state. Gitignored. Fully rebuildable via `dotscope rebuild`.

```
.dotscope/
  history.json           # Cached implicit contracts, stabilities, hotspots
  graph_hubs.json        # Cached cross-cutting hub analysis
  invariants.json        # Contracts, function co-changes, file stabilities
  sessions/              # Per-session JSON files (predictions)
  observations/          # Observation events from post-commit hooks
  regressions/           # Frozen successful sessions (regression test cases)
  near_misses.jsonl      # Detected near-misses
  utility_scores.json    # Per-file utility scores
  timings.jsonl          # Operation timing data (resolve, check, ingest)
  acknowledgments.jsonl  # Acknowledged holds with reasons
  onboarding.json        # Milestone tracking for stage-aware prompts
  last_session.json      # Scopes resolved in most recent session
```
