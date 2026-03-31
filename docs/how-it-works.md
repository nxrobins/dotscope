# How It Works

You run `dotscope init`. It scans your codebase. From that point on, every agent that touches your code gets the full picture — what files matter, what patterns to follow, what not to break, and who else is working.

## What happens when you run `dotscope init`

dotscope reads every file in your project and learns three things:

**Which files are connected.** If `billing.py` and `webhook_handler.py` always change together in your git history, dotscope knows. When an agent changes one, it gets told to check the other.

**What patterns your code follows.** If every file in `api/routes/` uses the same decorator and never touches the database directly, dotscope recognizes that as a convention. New files in that folder will follow the same pattern automatically.

**How your code is written.** Type hints on most functions? Google-style docstrings? No bare `except:` blocks? dotscope measures the style of your existing code and teaches agents to match it.

After the scan, dotscope:
- Installs git hooks so it stays up to date on every commit
- Registers an AST-aware merge driver for scoped files
- Connects to your AI tool (Claude Desktop, Claude Code, or Cursor) automatically
- Shows you what it would have caught in your last 50 commits

## What agents see

When an agent starts working on your code, it asks dotscope: "What do I need to know about this part of the project?"

dotscope responds with:
- **The right files** — not the whole repo, just the ones that matter for this task
- **The rules** — which files are connected, what patterns to follow, what imports are off-limits
- **The style** — how the existing code is written, so new code matches
- **The locks** — which files other agents are working on right now

The agent gets all of this before writing a single line. It writes code that fits in on the first try.

## What happens when something goes wrong

Before every commit, dotscope checks the agent's work:

- **Holds** (blocking) — The agent modified a backend endpoint without updating the frontend consumer. Or it wrote to a file locked by another agent. Or it violated a frozen module. The commit is stopped. The agent fixes it or acknowledges the override with an audit trail.
- **Notes** (informational) — A low-confidence link was flagged, or a file could live in a better directory. Worth knowing, not worth blocking.

Most of the time, nothing fires. The routing is good enough that agents follow the rules without needing to be corrected.

## It sees across languages

Your Python backend and your TypeScript frontend share an invisible contract: the HTTP API. dotscope sees both sides.

When an agent modifies a Django ViewSet that serves `/api/documents/`, dotscope knows that `document-list.component.ts` calls that endpoint. If the agent changes the backend without updating the frontend, the commit is blocked.

This works for FastAPI, Flask, Django REST Framework (including class-based ViewSets), Angular `HttpClient`, React, and any fetch/axios call. dotscope extracts routes and HTTP calls from the AST and links them with confidence scoring:

- **1.0** — exact regex match (decorator path matches fetch URL)
- **0.8** — suffix-aligned match (handles base URL differences)
- **0.5** — semantic root match (`DocumentViewSet` linked to `/api/document-types/`)

High-confidence matches (>= 0.8) block the commit. Low-confidence matches (0.5) surface as informational notes.

## It knows where files go

Agents dump utility functions in `src/utils/` and helpers in `src/helpers/`. Six months later, nobody can find anything.

dotscope prevents this with two rules derived from the dependency graph:

- **Orphan Rule** — If a file is only imported by one other file, it should live in the same directory as its parent.
- **Shared Rule** — If a file is imported from multiple directories, it should live at their lowest common ancestor.

Before an agent creates a file, it can ask:

```
dotscope_route_file("Stripe webhook retry task", imports=["domains.billing.models"])
→ domains/billing/tasks/
```

If an agent ignores the suggestion, the commit gets a note with a ready-to-apply `git mv` + AST-safe import rewrites across all dependent files.

On new projects, dotscope scaffolds a clean domain-driven structure from the first commit.

## It coordinates multiple agents

When two agents work on the same codebase at the same time, they will eventually touch the same file. dotscope prevents this with the Swarm Lock — a semantic mutex built on the dependency graph.

When Agent A claims a scope, dotscope computes the **blast radius** — not just the files Agent A asked for, but everything connected to them:

- **Depth 1** (direct dependents, network consumers, high-confidence co-change partners) — exclusively locked. Other agents cannot modify these.
- **Depth 2** (two-hop dependents) — shared lock with warnings. Other agents can read but get a warning before writing.
- **Depth 3+** — no lock. If two agents happen to modify the same function, the AST merge driver handles it.

Locks expire after 30 minutes. Agents can renew them. If a lock-related conflict fails to resolve after 2 attempts, dotscope escalates to a human operator with the full conflict state.

## It merges code semantically

When two agents legitimately modify the same file — say Agent A edits `get_user()` and Agent B adds `delete_user()` — Git's line-level merger often breaks. dotscope replaces it with an AST-aware merge driver.

The merge driver:
1. Extracts named mutations from each agent's diff (function edits, class changes, import additions)
2. Checks for conflicts (same function modified by both → halt)
3. Merges imports using set logic: `(Ancestor - Removed_A - Removed_B) ∪ Added_A ∪ Added_B`
4. Reconstructs the source in two passes: reverse-order replacements (no offset drift), then fresh insertion targets for additions
5. Runs contract verification on the merged result before accepting

The driver is registered via `.gitattributes` — only files in active scopes use it. Everything else falls through to Git's default merger.

## It gets smarter over time

Every commit teaches dotscope something. Did the agent need a file that wasn't included? Next time, it will be. Did a convention hold up across 50 commits? Its enforcement gets stronger. Did a rule get overridden three times in a month? It gets quieter.

You don't need to configure any of this. It happens automatically through the git hooks installed during `dotscope init`.

## What you can customize

dotscope works out of the box, but you can tune it:

**Freeze a module.** If you have stable code that agents shouldn't touch:
```
dotscope intent add freeze core/
```
Any change to `core/` will be blocked until acknowledged.

**Deprecate a file.** If you're migrating away from old code:
```
dotscope intent add deprecate utils/legacy.py --replacement utils/helpers.py
```
Agents that try to import from the old file get redirected.

**Edit conventions.** dotscope discovers conventions automatically, but you can add your own or adjust the ones it found. They live in `intent.yaml` at the root of your project.

## What gets created

dotscope creates two kinds of files:

**`.scope` files** (one per folder) — These describe what an agent needs to know about that part of your code. Commit them. They're your project's memory.

**`.dotscope/` folder** — Machine state: utility scores, swarm locks, cached graphs, network edges. Gitignored. Rebuilds automatically if deleted.

Both are plain text. You can read them, edit them, or ignore them entirely.

## Languages supported

Python, JavaScript, TypeScript, and Go get full analysis — every function, every class, every import relationship mapped. Python and JS/TS also get cross-language network contract detection (backend routes linked to frontend API calls) and AST-aware merging.

Other languages get basic import detection (enough for the dependency graph and git history analysis, but no convention or style discovery).

## Further reading

- [The .scope File](scope-file.md) — what's inside a scope file and how to edit it
- [MCP Server Setup](mcp-setup.md) — manual setup for AI tools (usually not needed after `dotscope init`)
- [CLI Reference](cli-reference.md) — every command dotscope offers
- [Architecture](architecture.md) — how dotscope itself is built (for contributors)
