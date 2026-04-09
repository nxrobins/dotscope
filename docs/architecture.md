# Dotscope Systems Architecture

To reliably route deterministic context to probabilistic LLMs across repositories with over 100,000 components, an standard language server (LSP) or Python monolithic execution layer will catastrophically buckle. An architecture must map topological reality in memory significantly faster than the host IDE can write to disk.

The Dotscope physical layout solves this by strictly isolating the intensive Write-Plane from the hyper-fast Read-Plane utilizing Multi-Version Concurrency Control (MVCC) bounds over Windows native page caching.

## The Write / Read Bifurcation

### 1. The Write-Plane (Rust OS Daemon)
To circumvent the Python Global Interpreter Lock (GIL) and isolate heavy Abstract Syntax Tree (AST) tree-sitter scanning entirely from the MCP interface, Dotscope utilizes `dotscope_daemon.exe`.

- **Execution Model:** The daemon acts continuously in the background, anchoring natively using `notify` directly on `.git` and `.ts`/`.py` changes. It abstracts standard single-thread IO into massively concurrent thread pools computing $O(V + E)$ dependency edge bounds. 
- **The Output:** It compiles the resolved dependency arrays strictly into `topology_A.bin` and `topology_B.bin`.

### 2. The Read-Plane (Zero-Copy Python Cast)
To solve the AI Agent "Cold Start" problem commonly caused when Cursor or Windsurf drop and re-initialize MCP endpoints unexpectedly, Dotscope isolates context delivery to an instantaneous memory layer.

- When `mcp` evaluates a state function, it maps the pre-calculated `topology.bin` bounds securely into memory mapping directly. 
- Using standard `struct.unpack(f'<{N}I')`, Python natively maps C-aligned arrays in nanoseconds fundamentally bypassing internal object allocation. Time-to-State generation is effectively 0 CPU cycles.

## Multi-Version Concurrency Control (The Epoch Lock)

Windows Native NTFS filesystem locks rigidly forbid symlink swap behavior commonly used to resolve double buffer pointers across OS variants. To ensure the daemon does not crash out updating pointers:

Dotscope anchors the deployment through a 4KB semantic Semaphore (`control.mmap`). 
This guarantees true **Read-Copy-Update (RCU)** limits gracefully: 
1. The daemon sets the atomic `DIRTY_FLAG` byte inside `control.mmap` upon receiving an IDE trigger sequence. 
2. It writes strictly to the inactive secondary `.bin` buffer.
3. Upon finalizing the 200ms `compilation` loop, it atomics the `active_buffer` indexing byte simultaneously with generating the numeric `EPOCH_VERSION`, triggering Python `ACTIVE_READERS` decrement mapping perfectly avoiding NTFS system locks.

### Auto-Upgrading Locks
Because LLMs hallucinate state easily if a file changes while they are browsing memory structures, the underlying Python `@mcp_tool_route` evaluates the `.mmap` `DIRTY_FLAG` byte automatically. If an agent tries to navigate code during a live Daemon compilation cycle, Dotscope instantly transforms its execution from a pure memory cast into an active TCP Unix socket block. The MCP Server formally locks the AI pipeline safely via `127.0.0.1` locally, only returning the payload exactly once the architecture converges definitively.
