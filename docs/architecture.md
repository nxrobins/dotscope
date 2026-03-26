# Architecture

dotscope is structured as an agentic compiler. Data definitions (Nouns), analysis operations (Verbs), and persistence (Memory).

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
│   └── sentinel/        #   Routing engine (8 checks, constraints, decay)
├── storage/             # How the compiler remembers
│   ├── session_manager.py     # Session + observation persistence
│   ├── cache.py               # Cached analysis data
│   ├── git_hooks.py           # Pre-commit routing + post-commit feedback
│   ├── claude_hooks.py        # Claude Code PreToolUse hook
│   ├── mcp_config.py          # Auto-detect IDE, write MCP config
│   ├── onboarding.py          # Stage-aware milestone tracking
│   ├── timing.py              # Operation instrumentation
│   ├── near_miss.py           # Near-miss detection persistence
│   └── incremental_state.py   # Continuous ingest drift tracking
├── progress.py          # Streaming progress emitter
├── help.py              # Hand-written help text
├── cli.py               # Human interface
└── mcp_server.py        # Agent interface
```

The Nouns live in `models/`. The Verbs live in `passes/`. The Memory lives in `storage/`. The Interfaces are at the root.

## Design Principles

**Routing, not enforcement.** Constraints at resolve time are the bowling bumpers. Checks at commit time verify the bumpers worked. Only frozen modules and deprecated imports hard-block.

**Severity levels:** GUARD (blocks commit), NUDGE (prints guidance, passes through), NOTE (informational). Nudges that fire 3+ times auto-escalate to GUARD.

**Zero dependencies.** Python 3.9+ stdlib only. Cross-platform.

## What's in `.dotscope/`

Runtime state. Gitignored. Fully rebuildable via `dotscope ingest .`.

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
  nudge_occurrences.jsonl # NUDGE escalation tracking
  timings.jsonl          # Operation timing data
  acknowledgments.jsonl  # Acknowledged guards with reasons
  onboarding.json        # Milestone tracking
  last_session.json      # Scopes resolved in most recent session
```
