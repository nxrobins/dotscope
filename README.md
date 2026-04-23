# Dotscope: The Physics Engine for AI Coding Agents

If you've used AI coding agents (Claude, Cursor, Windsurf), you've probably watched them blindly hallucinate an import or break a downstream service because they don't understand the blast radius of their changes. Standard search is lexically blind.

We built Dotscope to fix this. It’s a bare-metal structural compiler written in Rust that maps the explicit dependencies and temporal coupling (Git history) of your codebase, and force-feeds that "architectural gravity" into the agent's context window. The agent just stops breaking things. 

Supported natively via the Model Context Protocol (MCP) on Cursor, Windsurf, and Claude Desktop, Dotscope operates entirely locally, evaluates bounds near-instantly, and requires zero manual UI. 

---

## Installation (Now Zero-Dependency Setup)

We recently overhauled our distribution pipeline. `pip install dotscope` automatically pulls pre-compiled, native `PyO3` Rust wheels globally for Apple Silicon, Intel macOS, Linux, and Windows. You do not need to install a local `rustc` compiler. Day One is an instant binary installation.

```bash
# 1. Install the core toolkit
pip install dotscope[mcp]

# 2. Bind your repository and trigger the bare-metal physics engine
dotscope init

# 3. Verify the MCP boot contract
dotscope doctor mcp --check --json
```

`dotscope init` now enforces a repository boot contract for MCP startup: a working managed runtime, a passing stdio self-test, current repo-local MCP configs, and durable diagnostics in `.dotscope/mcp_install.json` and `.dotscope/mcp_last_failure.json`.

---

## Architectural Rigor: The FFI Topology Graph

Dotscope isn't a wrapper; it is an optimized topological execution plane engineered to map planetary-scale structures. Standard agents rely on simple string searching which leads to broken logic in large codebases. Dotscope natively hooks into `petgraph`, calculates the precise in-degree topological gravity of files, and pushes strict limits across the Python FFI via zero-copy vectors. 

**The Benchmark:**
- **Execution Time:** ~32 seconds for an entire 100,000 file ingestion.
- **Memory Ceiling:** Bounded strictly to 208MB RAM.
- **Concurrency:** Fully isolates multi-threaded file writes natively using a Token Bucket architecture to debounce IDE "save-spam," deploying atomic locks so memory never tears natively across agent requests.

---

## The Feedback Loop

You do not need to teach your AI a new paradigm. The AI simply searches the codebase exactly as it normally does. 

Under the hood, Dotscope intercepts the query and dynamically calculates physical constraints. If an agent touches a file with a `gravity_score > 50` (massive downstream blast-radius), Dotscope silently injects a `[DOTSCOPE_GRAVITY_WARNING]` constraint directly into the JSON-RPC stream, forcing the LLM to structurally verify impact before ever returning a line of logic to you.

The AI stops acting like a junior parsing text and starts acting like a senior respecting architecture.

---

## Scaling to the Swarm (Coming Soon)


### Dotscope Pro: The Genesis Matrix
Open-source Dotscope calculates the physical layout of your local codebase in realtime. **Dotscope Pro** is the global intelligence vector. By connecting to the Pro WebSocket, your agents don't have to compile graphs from scratch; they instantly stream pre-compiled structural fingerprints from over 10,000 top-tier open-source architectural hubs. Your agent doesn't just know how *you* construct code, it mathematically recognizes how *the planet* constructs it natively across boundaries.

### Dotswarm: Fleet Telemetry & Swarm Locks
What happens when you deploy 50 autonomous agents against a single enterprise monorepo infrastructure? They clobber each other's execution states. **Dotswarm** lifts our zero-latency local MVCC synchronization primitives directly into a distributed backend. It formally enforces **Swarm Locks** across distributed memory pools, guaranteeing massive AI fleets can orchestrate cross-repository execution simultaneously without triggering catastrophic merge collisions.
