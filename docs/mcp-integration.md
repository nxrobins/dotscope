# MCP Integration Guide

dotscope exposes codebase intelligence as MCP tools. Any MCP-compatible client can use the same local stdio server for scope discovery, architectural context, sync, health, and enforcement.

## Install

```bash
pip install dotscope[mcp]
```

This installs the `dotscope-mcp` launcher.

## Quick Start

```bash
# 1. Ingest your codebase
cd /path/to/your/project
dotscope ingest .

# 2. Repair the MCP boot contract
dotscope init --repair

# 3. Read-only verification for CI or diagnostics
dotscope doctor mcp --check --json
```

`dotscope init` now enforces a boot contract: a healthy managed runtime, a passing stdio self-test, current repo-local MCP configs, and durable diagnostics under `.dotscope/`.

`dotscope doctor mcp` uses the same pipeline with narrower defaults:

- Managed runtime: repaired by default
- Repo-local MCP configs: repaired by default
- Global client configs: advisory by default, repaired only with `--repair-global`

Repo-local targets enforced by the contract:

- `.mcp.json`
- `.claude/settings.json`
- `.vscode/mcp.json`
- `.cursor/mcp.json`
- `.codex/config.toml`

Supported global targets observed in cycles 1-2:

- Claude Desktop config
- Windsurf config

JetBrains and Zed remain documented/manual targets in cycles 1-2.

## Durable Diagnostics

Successful verification updates:

```text
.dotscope/mcp_install.json
```

That manifest records the selected launcher, managed-runtime identity, last successful verification, probe timings, repo-local target states, observed global target states, and the last repair mode.

Any nonzero MCP setup or doctor exit writes:

```text
.dotscope/mcp_last_failure.json
```

The failure bundle captures the failing phase, launcher argv, protocol attempts, stderr snippet, timings, target states, root-cause classification, and the exact next command to run.

## Manual Configuration

If you configure a client by hand, do not rely on bare `dotscope-mcp` on `PATH`. First ask dotscope which launcher it validated:

```bash
dotscope doctor mcp
```

Then use that absolute command and include:

```text
--root /path/to/your/project
```

### Claude Desktop

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`  
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "/absolute/path/to/dotscope-mcp",
      "args": ["--root", "/path/to/your/project"]
    }
  }
}
```

### Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "/absolute/path/to/dotscope-mcp",
      "args": ["--root", "/path/to/your/project"]
    }
  }
}
```

Claude Code still requires project-scope approval before first use.

### VS Code

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "dotscope": {
      "command": "/absolute/path/to/dotscope-mcp",
      "args": ["--root", "/path/to/your/project"]
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "dotscope": {
      "command": "/absolute/path/to/dotscope-mcp",
      "args": ["--root", "/path/to/your/project"]
    }
  }
}
```

### Custom Agents

Any stdio-capable MCP client can launch dotscope directly:

```bash
/absolute/path/to/dotscope-mcp --root /path/to/project
```

## Reliability Notes

Most activation failures came from one of these conditions:

- the client launched a different Python environment than the one that actually had `mcp` installed
- the server started outside the repository and could not discover `.git`, `.scopes`, or `.scope`
- the client config had drifted to an old JSON shape or a stale launcher path
- the server spent too long waiting on a strong-consistency MVCC path and the client marked it unhealthy

The current startup path addresses those cases by:

- installing a dotscope-owned runtime instead of depending on ambient Python state
- validating the selected launcher with a real stdio self-test before declaring the boot contract healthy
- emitting absolute command paths instead of bare `dotscope-mcp`
- forcing `--root` in every generated client config
- honoring `DOTSCOPE_ROOT` on the server side as an extra fallback
- bounding strong MVCC waits for MCP calls

## Command Meanings

```bash
dotscope init
```

Repairs the managed runtime and repo-local boot contract. It may also rewrite detected supported global configs.

```bash
dotscope init --repair
```

Forces runtime reprovisioning, reprobe, and config rewrites even if current state appears healthy.

```bash
dotscope doctor mcp
```

Repairs the managed runtime plus repo-local configs. Global drift is advisory by default and does not fail the command by itself.

```bash
dotscope doctor mcp --check
```

Read-only verification mode for CI and diagnostics.

```bash
dotscope doctor mcp --repair-global
```

Extends doctor repairs to supported global configs.

## Tools Reference

dotscope exposes the following MCP tool families:

- Discovery: `dotscope_search`, `match_scope`, `list_scopes`
- Resolution: `resolve_scope`, `get_context`
- Enforcement: `dotscope_check`
- Analysis: `scope_health`, `validate_scopes`
- Operations: `ingest_codebase`, `dotscope_sync`, `dotscope_refresh`
- Multi-agent: `dotscope_claim_scope`, `dotscope_renew_lock`, `dotscope_escalate`

## Recommended Agent Workflow

```text
1. dotscope_search("fix the auth token refresh bug")
2. resolve_scope("auth", task="fix token refresh")
3. [write code]
4. dotscope_check()
5. [self-correct if needed]
6. [commit]
```
