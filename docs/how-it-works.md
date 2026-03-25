# How It Works

dotscope builds `.scope` files by analyzing three things about your codebase: its dependency graph, its git history, and its existing documentation. Then it validates what it built against your commit history and tells you how accurate it is. After that, it watches what actually happens during agent sessions and corrects itself.

## The Ingest Pipeline

`dotscope ingest .` runs five steps:

**1. Dependency graph.** Static analysis of imports and references across all files. Produces a directed graph of which files depend on which. This determines module boundaries, identifies cross-cutting hubs (files imported by many modules), and computes transitive blast radius for any file.

**2. History mining.** Analyzes your git log (last 200 commits by default) to extract patterns that aren't visible in the code itself: which files change together (implicit contracts), how volatile each file is (stability profiles), and which areas of the codebase are hotspots for churn.

**3. Document absorption.** Reads READMEs, docstrings, and signal comments (lines containing `SCOPE:`, `CONTEXT:`, `GOTCHA:`, or similar markers). Extracts the knowledge that a human put into prose but that an agent would otherwise never see.

**4. Scope generation.** For each module (top-level directory with Python files), synthesizes a `.scope` file. The `includes` list comes from the dependency graph. The `context` field is assembled from implicit contracts, stability profiles, absorbed documentation, dependency information, and recent changes — in that priority order.

**5. Backtest validation.** Replays recent commits against the generated scopes: for each historical commit, would the scope have pointed the agent at the right files? Reports overall recall, per-scope recall, and token reduction ratio. If a scope scores poorly, auto-correction adjusts its includes and reruns the test.

After ingest, structured analysis data is cached in `.dotscope/` (history, graph hubs) so the MCP server can use it at runtime without re-computing.

## The .scopes Index

Ingest also writes a `.scopes` file at the project root. This is the index that maps scope names to paths and stores project-wide metadata like `total_repo_tokens`. The MCP server reads this on startup to know what's available.

## Scope Resolution

When an agent calls `resolve_scope` (via MCP) or a developer runs `dotscope resolve`, the resolver:

1. Parses the scope expression (supports algebra: `auth+payments` for union, `auth&payments` for intersection, `auth-tests` for difference)
2. Loads the matching `.scope` file(s)
3. Applies any token budget constraint (`--budget 4000` returns the highest-utility subset)
4. Returns files, context, attribution hints, accuracy data, health warnings, and near-misses

Token budgeting uses utility scores that improve over time through the observation loop.

## Scope Algebra

Scope expressions let agents and developers combine scopes:

```
auth                  # Single scope
auth+payments         # Union: files from both
auth&payments         # Intersection: files in both
auth-tests            # Difference: auth minus test files
auth@context          # Projection: context only, no files
auth@files            # Projection: files only, no context
```

These compose. `(auth+payments)@context` returns the combined context from both scopes without file lists.

## Virtual Scopes

When ingest detects a file that is imported across many modules (a cross-cutting hub), it generates a virtual scope for that file. Virtual scopes don't correspond to a directory — they represent a single high-impact file and its transitive dependents. This ensures agents get context about shared infrastructure even when working within a single module.

## The Feedback Loop

Most context tools are static: generate once, hope for the best. dotscope closes a feedback loop that makes scopes improve with use.

**Prediction.** Every `resolve_scope` call is a prediction: "these are the files and context the agent needs for this task." The session tracker records what was served.

**Observation.** After the agent commits (`dotscope hook install` sets up a post-commit hook), dotscope compares what the agent actually touched against what the scope predicted. This produces an accuracy score and identifies missing files.

**Learning.** Observation data updates utility scores for every file in every scope. Files that are consistently touched get higher utility. Files that are included but never touched get lower utility. The next `resolve_scope` call with a budget will rank files differently.

**Correction.** Over time, scopes that start as documentation become intelligence. The post-commit hook prints a delta so you can watch it happen:

```
dotscope: observation recorded for auth/
  auth/ predicted 7/8 files correctly (88%)
  Missing: tokens.py
  Utility scores updated
```

## Backtest Validation

`dotscope backtest --commits 500` replays historical commits against current scopes without modifying anything. It answers: "If these scopes had existed during the last 500 commits, how often would the agent have had the right files?"

Reports two metrics: **recall** (did the scope include the files that were actually changed?) and **token reduction** (how much smaller is the scope compared to feeding the agent the entire repo?). These are the numbers that build trust.

## Health Monitoring

`dotscope health` checks every scope for staleness, accuracy degradation, and uncovered files. Health warnings also surface automatically during `resolve_scope` calls — the agent will mention them if a scope it's using has degraded.

Health nudges fire on resolve only, never on ingest. If you just regenerated a scope, warning about its staleness would be noise.

## Near-Miss Detection

After a commit, dotscope checks whether the agent avoided a mistake that the scope context warned about. If the scope says "never call .delete() on User, use .deactivate()" and the commit diff contains `.deactivate()` but not `.delete()`, that's a near-miss. These surface in both the terminal and the next `resolve_scope` response.

## What's in `.dotscope/`

The `.dotscope/` directory stores runtime state. It's gitignored and fully rebuildable.

```
.dotscope/
  history.json          # Cached implicit contracts, stabilities, hotspots
  graph_hubs.json       # Cached cross-cutting hub analysis
  observations.jsonl    # Observation events from post-commit hooks
  near_misses.jsonl     # Detected near-misses
  last_session.json     # Scopes resolved in most recent agent session
  utility_scores.json   # Per-file utility scores (updated on every observation)
```

`dotscope rebuild` regenerates everything in `.dotscope/` from the event log if you ever need to start fresh.
