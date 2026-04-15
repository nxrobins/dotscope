# MCP Integration Guide

dotscope exposes codebase intelligence as MCP tools. Any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Windsurf, or any custom agent) gets compiled context, architectural constraints, and self-correcting feedback through a single protocol.

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
dotscope init

# 3. Verify — ask your agent: "What scopes are available?"
```

`dotscope init` detects Claude Desktop, Claude Code, and Cursor, and writes the MCP entry automatically. For other clients, see manual setup below.

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

Add to `.mcp.json` in your project root:

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

### Custom Agents

Any MCP client that supports stdio transport:

```bash
dotscope-mcp --root /path/to/project
```

The server speaks MCP over stdin/stdout. Point your client at the binary.

---

## Tools Reference

dotscope exposes 14 MCP tools organized into five categories.

### Discovery

| Tool | Use When |
|------|----------|
| `dotscope_search` | You have a task and need relevant code. **Start here.** Returns grep matches enriched with structural gravity and dependency data. |
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

### Analysis

| Tool | Use When |
|------|----------|
| `scope_health` | Checking for staleness, coverage gaps, import drift. |
| `validate_scopes` | Checking for broken paths and missing context. |

### Operations

| Tool | Use When |
|------|----------|
| `ingest_codebase` | First-time setup or full re-scan from within the agent. |
| `dotscope_sync` | After adding/moving/deleting source files. Re-aligns .scope boundaries against the real AST topology. |
| `dotscope_refresh` | After manual edits to .scope files. Reloads the runtime cache. |

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
1. dotscope_search("fix the auth token refresh bug")
   -> Returns files with architectural gravity and dependency context

2. resolve_scope("auth", task="fix token refresh")
   -> Returns ranked files, context, constraints, voice

3. [Agent writes code]

4. dotscope_check()
   -> Validates against contracts, conventions, anti-patterns
   -> GUARDs block the commit. NUDGEs suggest corrections.

5. [Agent self-corrects if needed]

6. [Commit]
```

For known scopes, skip step 1 and go directly to `resolve_scope`.

---

## The Resolve Response

When you call `resolve_scope`, you get back a structured response:

```json
{
  "files": ["auth/handler.py", "auth/tokens.py", "models/user.py"],
  "context": "JWT tokens with 15-min access / 7-day refresh...",
  "token_estimate": 1420,
  "scope_chain": ["auth/.scope"],
  "file_count": 3
}
```

**`files`** are ranked by relevance and fitted to your token budget. Trust the ranking.

**`context`** is architectural knowledge: invariants, gotchas, conventions, decisions.

**`attribution_hints`** explain where the knowledge came from. Sources: `git_history`, `hand_authored`, `signal_comment`, `graph`.

**`voice`** is how the codebase writes code. Style conventions, type hint adoption, docstring format.

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
      "suggestion": "Review api/auth_routes.py for necessary changes"
    }
  ],
  "notes": [],
  "files_checked": 3
}
```

**`guards`** block the commit. Frozen modules, deprecated imports, hard boundary violations.

**`nudges`** are course corrections. Contract mismatches, convention drift, anti-pattern warnings. The commit is not blocked.

**`notes`** are informational. No action required.

---

## Multi-Agent Workflow

When multiple agents work on the same codebase simultaneously, use swarm locks to prevent conflicts.

```
Agent A                          Agent B
   |                                |
   +- dotscope_search(...)          |
   +- dotscope_claim_scope(         |
   |    agent_id="agent-a",         |
   |    primary_files=[             |
   |      "auth/handler.py"])       |
   |  -> status: "granted"          |
   |                                +- dotscope_claim_scope(
   |                                |    agent_id="agent-b",
   |                                |    primary_files=[
   |                                |      "auth/handler.py"])
   |                                |  -> status: "rejected"
   |                                |
   |  [writes code]                 |  [works on different scope]
   +- dotscope_check()              |
   +- [commit]                      |
   |  -> lock released              +- dotscope_claim_scope(...)
                                    |  -> status: "granted"
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

## Troubleshooting

**"No scopes found"**
Run `dotscope ingest .` first. The `list_scopes` command requires .scope files to exist.

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
Run `dotscope sync` to re-align .scope boundaries against the current import graph. Run `dotscope ingest .` for a full re-scan.

**Windows encoding errors**
dotscope uses UTF-8 everywhere with ASCII fallbacks for cp1252 terminals. If you see encoding errors, set `PYTHONIOENCODING=utf-8` in your environment.
