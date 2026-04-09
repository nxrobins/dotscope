# Setting Up Dotscope for MCP Environments

Despite executing a rigidly isolated zero-copy Multi-Version Concurrency Control (MVCC) daemon architecture, deploying Dotscope locally remains fully frictionless, explicitly requiring absolutely zero configuration files or external orchestration containers. 

It is the **Invisible Supremum**. 

## Agent Integration

Whether deploying on **Cursor**, **Windsurf**, or **Claude Desktop**, integrating the Model Context Protocol requires merely aiming the AI interface natively to your local installation directory explicitly via standard standard CLI execution targets:

`command: python -m dotscope`

### Zero-Configuration Networking
You do not need to boot Docker. You do not install WASM runtimes, and you actively do not configure open proxy routing addresses natively. 

When your IDE pings Dotscope for the first time, it implicitly spawns the `dotscope_daemon.exe` fully completely encapsulated in the background natively. To securely maintain concurrency limits across Python read boundaries, the daemon executes absolutely statically behind an invisible internal binding mapped entirely to `127.0.0.1`. 

Because Dotscope forces rigid `.cursorrules` parameters directly into the operational root via `dotscope init`, your IDE fundamentally syncs its execution behaviors automatically aligning completely uniformly across physical project changes gracefully!
