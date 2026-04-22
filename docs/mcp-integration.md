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

# 2. Auto-configure supported clients
dotscope init

# 3. Verify the launcher and configs
dotscope doctor mcp
```

`dotscope init` now installs a dotscope-owned MCP runtime, resolves a working launcher from that runtime, writes absolute-command MCP entries, and pins every generated config to the repository with `--root`.

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
- validating launcher candidates before writing configs
- emitting absolute command paths instead of bare `dotscope-mcp`
- forcing `--root` in every generated client config
- honoring `DOTSCOPE_ROOT` on the server side as an extra fallback
- bounding strong MVCC waits for MCP calls

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
