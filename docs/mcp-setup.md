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
dotscope init
dotscope doctor mcp
```

`dotscope init` now resolves a working launcher, writes absolute-command MCP configs for supported clients, and pins every generated entry to the repository with `--root`.
It also installs a dotscope-owned MCP runtime in a deterministic per-user location, so clients no longer depend on whichever Python environment happens to be first on `PATH`.

`dotscope doctor mcp` verifies the same launcher with a real MCP initialize and `tools/list` handshake, then reports whether the generated client configs are current or stale.

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
