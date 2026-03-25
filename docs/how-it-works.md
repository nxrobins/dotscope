# How It Works

dotscope builds `.scope` files by analyzing your dependency graph, git history, and existing docs. It validates them against your commit history. Then it watches what agents actually do, learns from every commit, enforces your codebase's rules, and tells you what it prevented.

## The Ingest Pipeline

`dotscope ingest .` runs five steps:

**1. Dependency graph.** Static analysis of imports across all files. Produces a directed graph: module boundaries, cross-cutting hubs (files imported by many modules), and transitive blast radius for any file. Python uses AST parsing; JS/TS/Go use enhanced regex.

**2. History mining.** Analyzes your git log (up to 500 commits) for patterns invisible in the code: implicit contracts (files that always change together), stability profiles, churn hotspots, and function-level co-change data.

**3. Document absorption.** Reads READMEs, docstrings, and signal comments (`SCOPE:`, `CONTEXT:`, `GOTCHA:` markers). Extracts knowledge a human wrote but an agent would never see.

**4. Scope generation.** For each module, synthesizes a `.scope` file. Includes come from the dependency graph. Context is assembled from implicit contracts, stability profiles, absorbed docs, dependency info, and recent changes — in that priority order.

**5. Backtest validation.** Replays recent commits: would the scope have pointed the agent at the right files? Reports recall per scope and token reduction. Auto-corrects low-scoring scopes and reruns.

After ingest, structured data is cached in `.dotscope/` (history, graph hubs, invariants) so the MCP server can use it at runtime without re-computing.

## Scope Resolution

When an agent calls `resolve_scope`:

1. Parse the scope expression (algebra: `auth+payments`, `auth-tests`, `auth&api`, `auth@context`)
2. Load the `.scope` file(s)
3. Inject lessons and invariants from the observation store into context
4. Apply token budget (files ranked by historical utility, then keyword relevance, then size)
5. Build filtered constraints (contracts, anti-patterns, boundaries, intents — relevant to this scope)
6. Return files, context, constraints, attribution hints, accuracy, health warnings, near-misses

## Enforcement

dotscope knows your codebase's rules. It surfaces them at three points:

**Prophylactic (at resolve time).** Every `resolve_scope` response includes a `constraints` field: implicit contracts, anti-patterns, dependency boundaries, stability warnings, and architectural intents. The agent knows the rules before writing code. Filtered to the resolved scope and capped at 5 per category to stay under 400 tokens.

**Diagnostic (before commit).** The agent calls `dotscope_check` with its diff. Returns structured holds (must address) and notes (informational), with fix proposals: predicted functions that need changes, or exact replacement diffs for anti-pattern violations.

**Gate (at commit time).** The post-commit hook runs the same checks. Terminal output shows holds and notes. Holds block the commit; notes are informational.

Six check categories:

| Category | Severity | What it catches |
|----------|----------|-----------------|
| Boundary violation | HOLD | Agent modified files outside its resolved scope |
| Implicit contract | HOLD | Coupled file modified without its pair |
| Anti-pattern | HOLD | Prohibited pattern in added lines |
| Dependency direction | NOTE | New import reversing established flow |
| Stability concern | NOTE | Large change to a stable file |
| Architectural intent | HOLD or NOTE | Change violating declared direction |

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

## Acknowledge Flow

Sometimes breaking a rule is correct:

```bash
dotscope check --acknowledge contract_auth_tokens_api_a1b2c3
```

Acknowledgments are recorded. 3+ acknowledgments of the same constraint within 30 days decay its confidence by 0.1 per excess. Below 0.5, the constraint becomes a NOTE instead of HOLD. Floor at 0.3 — core rules survive.

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
| First ingest | `Run dotscope check --backtest` |
| First backtest | `Add dotscope to your agent` |
| First MCP session | `Install the post-commit hook` |
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
