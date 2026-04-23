# Setting Up Dotscope for MCP Clients

## Install

```bash
pip install dotscope[mcp]
```

This installs the `dotscope-mcp` launcher that serves MCP over stdio.

## Recommended Setup

From your repository root:

```bash
dotscope ingest .
dotscope init --repair
dotscope doctor mcp --check --json
```

`dotscope init` now enforces an MCP boot contract: managed runtime repair, a real stdio self-test, repo-local config rewrites, and durable diagnostics in `.dotscope/mcp_install.json` and `.dotscope/mcp_last_failure.json`.

`dotscope doctor mcp` uses the same pipeline, but its default repair scope is narrower:

- Managed runtime: repaired by default
- Repo-local configs: repaired by default
- Global configs: advisory by default, repaired only with `--repair-global`

`dotscope doctor mcp --check` is the read-only variant for CI and diagnostics.

## Manual Setup

If you configure a client by hand, do not rely on bare `dotscope-mcp` being on `PATH`. Use the full launcher path reported by:

```bash
dotscope doctor mcp
```

Each stdio client entry should point at that absolute command and include:

```text
--root /absolute/path/to/your/repo
```

## Why This Matters

Most MCP activation failures were caused by one of two conditions:

- the client launched a different Python environment than the one that actually had `mcp` installed
- the server started outside the repository root and could not discover `.scopes`, `.git`, or `.scope`

Using an absolute launcher plus `--root` removes both failure modes.
Using a managed dotscope-owned runtime removes the first one almost entirely: the launcher and dependency set are now provisioned and verified by dotscope itself.

## Repo-Local vs Global Targets

Repo-local targets enforced by the boot contract:

- `.mcp.json`
- `.claude/settings.json`
- `.vscode/mcp.json`
- `.cursor/mcp.json`
- `.codex/config.toml`

Supported global targets in cycles 1-2:

- Claude Desktop config
- Windsurf config

JetBrains and Zed remain documented/manual targets in cycles 1-2.

## Failure Guidance

When an MCP setup or doctor command exits nonzero, dotscope writes:

```text
.dotscope/mcp_last_failure.json
```

The command also prints a stderr footer with that path and the exact next command to run.
