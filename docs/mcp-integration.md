# MCP Integration Guide

dotscope exposes codebase intelligence as MCP tools. Any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Codex, OpenClaw, or any custom agent) gets compiled context, architectural constraints, and self-correcting feedback through a single protocol.

## Install

```bash
pip install dotscope[mcp]
```

This installs the `dotscope-mcp` binary, which runs a stdio-transport MCP server.

## Quick Start

```bash
# 1. Ingest your codebase (one-time, ~10s for most repos)
cd /path/to/your/project
dotscope ingest .

# 2. Auto-configure your IDE
dotscope mcp configure

# 3. Verify — ask your agent: "What scopes are available?"
```

`dotscope mcp configure` detects Claude Desktop, Claude Code, and Cursor, and writes the MCP entry automatically. For other clients, see manual setup below.

## Manual Configuration

### Claude Desktop

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "dotscope-mcp",
      "args": ["--root", "/path/to/your/project"]
    }
  }
}
```

Restart Claude Desktop after editing.

### Claude Code

Add to `.claude/settings.json` in your project root:

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "dotscope-mcp"
    }
  }
}
```

No `--root` needed. Claude Code launches from the project directory.

### Cursor

Settings > MCP Servers, or `.cursor/mcp.json` in the project root:

```json
{
  "dotscope": {
    "command": "dotscope-mcp",
    "args": ["--root", "/path/to/your/project"]
  }
}
```

### OpenClaw

Add as an MCP tool in your OpenClaw config, or use the `dotscope` skill from ClawHub.

### Custom Agents

Any MCP client that supports stdio transport:

```bash
dotscope-mcp --root /path/to/project
```

The server speaks MCP over stdin/stdout. Point your client at the binary.

---

## Tools Reference

dotscope exposes 19 MCP tools organized into five categories.

### Discovery

| Tool | Use When |
|------|----------|
| `codebase_search` | You have a task and need relevant code. **Start here.** |
| `match_scope` | You have a task description, need to find which scope covers it. |
| `list_scopes` | You want to see all available scopes with descriptions. |

### Resolution

| Tool | Use When |
|------|----------|
| `resolve_scope` | You know the scope name and want files + context + constraints. |
| `get_context` | You want architectural knowledge without loading files. |

### Enforcement

| Tool | Use When |
|------|----------|
| `dotscope_check` | Before committing. Validates your diff against codebase rules. |
| `dotscope_acknowledge` | A constraint is wrong for your case. Override it with a reason. |
| `match_conventions_by_path` | Before creating a new file. See what patterns it should follow. |
| `dotscope_route_file` | Before creating a new file. Ask where it should live. |

### Analysis

| Tool | Use When |
|------|----------|
| `impact_analysis` | Before modifying a file. See the blast radius. |
| `scope_health` | Checking for staleness, coverage gaps, import drift. |
| `validate_scopes` | Checking for broken paths and missing context. |
| `backtest_scopes_tool` | Measuring recall against git history. |
| `scope_observations` | Reviewing accuracy trends for a scope. |
| `scope_lessons` | Getting machine-generated patterns from observation data. |
| `suggest_scope_changes` | Data-driven recommendations for scope includes. |

### Operations

| Tool | Use When |
|------|----------|
| `ingest_codebase` | First-time setup or full re-scan from within the agent. |
| `dotscope_debug` | A session went wrong. Diagnose why. |
| `session_summary` | End of task. See what dotscope contributed. |

### Multi-Agent (Swarm)

| Tool | Use When |
|------|----------|
| `dotscope_claim_scope` | Before writing code in a multi-agent setup. Claim exclusive access. |
| `dotscope_renew_lock` | Your lock is about to expire. Extend it. |
| `dotscope_escalate` | Interlocking conflicts that can't be resolved programmatically. |

---

## Primary Workflow

Most agent sessions follow this pattern:

```
1. codebase_search("fix the auth token refresh bug", task_type="fix")
   → Returns files, constraints, routing, action hints

2. [Agent writes code]

3. dotscope_check()
   → Validates against contracts, conventions, anti-patterns
   → GUARDs block the commit. NUDGEs suggest corrections.

4. [Agent self-corrects if needed]

5. [Commit]
   → Post-commit hook records what changed vs. what was predicted
   → Utility scores update. Next resolve is smarter.
```

For known scopes, replace step 1 with `resolve_scope("auth", task="fix token refresh")`.

---

## The Resolve Response

When you call `resolve_scope` or `codebase_search`, you get back a structured response. Here is what each field means and how to use it.

```json
{
  "scope": "auth/",
  "files": [
    "auth/handler.py",
    "auth/tokens.py",
    "models/user.py"
  ],
  "context": "JWT tokens with 15-min access / 7-day refresh...",
  "token_count": 1420
}
```

**`files`** are ranked by relevance and fitted to your token budget. Trust the ranking. Do not read files manually.

```json
{
  "constraints": [
    {
      "category": "contract",
      "message": "If you modify auth/tokens.py, review api/auth_routes.py",
      "confidence": 0.82
    },
    {
      "category": "anti_pattern",
      "message": "Use .deactivate() instead of .delete() on User",
      "confidence": 1.0
    }
  ]
}
```

**`constraints`** are things NOT to do. Implicit contracts from git history, anti-patterns, boundary rules. Check these before writing code.

```json
{
  "routing": [
    {
      "category": "routing",
      "message": "Files here follow the 'Repository' convention. Implement: get, save. Do not import: flask.",
      "confidence": 0.85
    }
  ]
}
```

**`routing`** is things TO do. Convention blueprints, naming rules, structural patterns. The agent reads this and writes code that fits on the first try.

```json
{
  "attribution_hints": [
    {
      "hint": "billing.py and webhook_handler.py have 73% co-change rate",
      "source": "git_history"
    }
  ]
}
```

**`attribution_hints`** explain where the knowledge came from. Sources: `git_history` (mined from commits), `hand_authored` (written by a human in the .scope file), `signal_comment` (extracted from code comments), `graph` (dependency analysis).

```json
{
  "accuracy": {
    "observations": 12,
    "avg_recall": 0.91,
    "trend": "improving",
    "lessons_applied": 3
  }
}
```

**`accuracy`** is self-reported scope performance. How well this scope's predictions matched actual agent behavior over time.

```json
{
  "voice": {
    "mode": "adaptive",
    "global": "Type hints on most functions (62% adoption). Google style docstrings."
  }
}
```

**`voice`** is how the codebase writes code. Style conventions, type hint adoption, docstring format. The agent matches this to produce code that looks native.

Additional fields: `health_warnings` (staleness alerts, refresh status), `near_misses` (files that were close to inclusion but didn't make the budget cut), `freshness` (whether the scope data is current).

---

## The Check Response

```json
{
  "passed": true,
  "guards": [],
  "nudges": [
    {
      "category": "implicit_contract",
      "severity": "nudge",
      "message": "auth/tokens.py modified without api/auth_routes.py (82% co-change)",
      "file": "auth/tokens.py",
      "suggestion": "Review api/auth_routes.py for necessary changes",
      "proposed_fix": {
        "file": "api/auth_routes.py",
        "reason": "When auth/tokens.py changes, these sections typically need updates",
        "predicted_sections": ["validate_token", "refresh_handler"],
        "confidence": 0.78
      }
    }
  ],
  "notes": [],
  "files_checked": 3
}
```

**`guards`** block the commit. Frozen modules, deprecated imports, hard boundary violations. These must be addressed.

**`nudges`** are course corrections. Contract mismatches, convention drift, anti-pattern warnings. The commit is not blocked. The agent reads them and self-corrects. `proposed_fix` includes predicted sections and sometimes a diff.

**`notes`** are informational. No action required.

---

## Multi-Agent Workflow

When multiple agents work on the same codebase simultaneously, use swarm locks to prevent conflicts.

```
Agent A                          Agent B
   │                                │
   ├─ codebase_search(...)          │
   ├─ dotscope_claim_scope(         │
   │    agent_id="agent-a",         │
   │    primary_files=[             │
   │      "auth/handler.py",       │
   │      "auth/tokens.py"         │
   │    ])                          │
   │  → status: "granted"          │
   │  → exclusive: [auth/*, ...]   │
   │                                ├─ codebase_search(...)
   │                                ├─ dotscope_claim_scope(
   │                                │    agent_id="agent-b",
   │                                │    primary_files=[
   │                                │      "auth/handler.py"
   │                                │    ])
   │                                │  → status: "rejected"
   │                                │  → conflict: agent-a holds auth/
   │                                │
   │  [writes code]                 │  [works on different scope]
   │                                │
   ├─ dotscope_check()              │
   ├─ [commit]                      │
   │  → lock released               │
   │                                ├─ dotscope_claim_scope(...)
   │                                │  → status: "granted"
```

Claims compute a blast radius from the dependency graph. Direct dependents get exclusive locks. Two-hop dependents get shared locks (advisory warnings, not blocking).

If locks interlock and neither agent can proceed, use `dotscope_escalate` to surface the conflict to a human operator.

---

## Scope Composition

`resolve_scope` accepts composition expressions for cross-cutting tasks:

| Expression | Meaning |
|---|---|
| `auth` | Single scope |
| `auth+payments` | Union of two scopes |
| `auth-tests` | Scope minus test files |
| `auth&api` | Intersection of two scopes |
| `auth@context` | Context only (no files) |

Composition is useful when a task spans scope boundaries. The token budget applies to the combined result.

---

## Task-Optimized Search

`codebase_search` accepts a `task_type` parameter that adjusts budget allocation:

| task_type | Optimization |
|---|---|
| `"fix"` | Boosts abstractions (understand the call chain to find the bug) |
| `"add"` | Boosts routing and conventions (write code that fits the architecture) |
| `"refactor"` | Boosts network edges and companions (understand the blast radius) |
| `"test"` | Boosts companions and abstractions (find related tests and interfaces) |
| `"review"` | Balanced with extra network edge context |

Always provide `task_type` when your objective is clear. It changes which files get priority within the budget.

---

## The Feedback Loop

dotscope improves with use. Here is what happens automatically:

1. **Post-commit observation:** The git hook records which files changed and compares against what was predicted. Recall and precision are computed per scope.

2. **Utility scoring:** Files agents consistently need get ranked higher in future resolves. Files that are always served but never touched get deprioritized.

3. **Lesson generation:** After enough observations, dotscope generates machine-learned lessons: "agents working on auth always need models/user.py" or "tokens.py changes never require webhook_handler.py changes despite the import."

4. **Self-correction:** Scope includes, rankings, and constraint confidence adjust based on accumulated data. No manual tuning required.

You can inspect this loop with `scope_observations`, `scope_lessons`, and `suggest_scope_changes`.

---

## Hooks

```bash
dotscope hook install
```

Installs two git hooks:

| Hook | When | What | Blocks? |
|---|---|------|---------|
| `pre-commit` | Before every commit | `dotscope check` on staged changes | GUARDs only |
| `post-commit` | After every commit | `dotscope observe` + `dotscope incremental` | Never |

For Claude Code, an additional hook intercepts commits at the tool level:

```bash
dotscope hook claude
```

This writes to `.claude/settings.json` and provides defense-in-depth. The git pre-commit hook is sufficient for most setups.

---

## Generated Documentation

dotscope can produce architecture documentation from its analysis:

```bash
dotscope generate
```

Or via MCP: `generate_artifacts()`

This produces three markdown files in `docs/dotscope/`:

| File | Contents |
|------|----------|
| `ARCHITECTURE_CONTRACTS.md` | Implicit contracts discovered from git co-change analysis |
| `NETWORK_MAP.md` | Cross-scope dependency map with traffic patterns |
| `CO_CHANGE_ATLAS.md` | Which files change together, how often, and why |

These are useful for onboarding, code review, and architecture discussions. They update when you re-run `dotscope generate`.

---

## Troubleshooting

**"No scopes found"**
Run `dotscope ingest .` first. If you call `resolve_scope` on a specific module before ingesting, dotscope will lazy-ingest it on demand (2-3 seconds), but `list_scopes` requires an initial ingest.

**Agent does not see dotscope tools**
Check that `dotscope-mcp` is on your PATH:
```bash
which dotscope-mcp    # macOS/Linux
where dotscope-mcp    # Windows
```
Run it directly to check for import errors:
```bash
dotscope-mcp --root .
```

**Stale scope data**
Scopes update incrementally on every commit via the post-commit hook. For a full re-scan (transitive deps, convention re-discovery), run `dotscope ingest .` again.

**Token budget too small**
If `resolve_scope` returns a `context_exhaustion` error, the budget cannot fit a required file. Increase the budget or remove the assertion. The error tells you exactly which file and how many tokens it needs.

**Windows encoding errors**
dotscope uses UTF-8 everywhere with ASCII fallbacks for cp1252 terminals. If you see encoding errors, set `PYTHONIOENCODING=utf-8` in your environment.

---

## Architecture Note

dotscope's MCP server is stateless between sessions but stateful within a session. Each session tracks:

- Which scopes were resolved
- Which constraints were served
- Token counts and reduction metrics
- Counterfactuals (what dotscope prevented)

On server shutdown, a session summary prints to stderr. Call `session_summary()` from within the agent to get this data programmatically.

The server reads from `.dotscope/` (cached analysis data) and writes observation data back via git hooks. The MCP server itself never modifies your source code or .scope files.
