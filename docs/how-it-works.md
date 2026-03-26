# How It Works

You run `dotscope init`. It scans your codebase. From that point on, every agent that touches your code gets the full picture — what files matter, what patterns to follow, and what not to break.

## What happens when you run `dotscope init`

dotscope reads every file in your project and learns three things:

**Which files are connected.** If `billing.py` and `webhook_handler.py` always change together in your git history, dotscope knows. When an agent changes one, it gets told to check the other.

**What patterns your code follows.** If every file in `api/routes/` uses the same decorator and never touches the database directly, dotscope recognizes that as a convention. New files in that folder will follow the same pattern automatically.

**How your code is written.** Type hints on most functions? Google-style docstrings? No bare `except:` blocks? dotscope measures the style of your existing code and teaches agents to match it.

After the scan, dotscope:
- Installs git hooks so it stays up to date on every commit
- Connects to your AI tool (Claude Desktop, Claude Code, or Cursor) automatically
- Shows you what it would have caught in your last 50 commits

## What agents see

When an agent starts working on your code, it asks dotscope: "What do I need to know about this part of the project?"

dotscope responds with:
- **The right files** — not the whole repo, just the ones that matter for this task
- **The rules** — which files are connected, what patterns to follow, what imports are off-limits
- **The style** — how the existing code is written, so new code matches

The agent gets all of this before writing a single line. It writes code that fits in on the first try.

## What happens when something goes wrong

Before every commit, dotscope checks the agent's work:

- **Blocks** (rare) — The agent tried to modify a frozen module or use deprecated code. The commit is stopped. The agent fixes it.
- **Nudges** (common) — The agent changed a file without updating its counterpart, or drifted from a convention. The agent sees the guidance and self-corrects.
- **Notes** (informational) — Something worth knowing but not worth blocking.

Most of the time, nothing fires. The routing is good enough that agents follow the rules without needing to be corrected.

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

**`.dotscope/` folder** — Machine state. Gitignored. Rebuilds automatically if deleted.

Both are plain text. You can read them, edit them, or ignore them entirely.

## Languages supported

Python, JavaScript, TypeScript, and Go get full analysis — every function, every class, every import relationship mapped.

Other languages get basic import detection (enough for the dependency graph and git history analysis, but no convention or style discovery).

## Further reading

- [The .scope File](scope-file.md) — what's inside a scope file and how to edit it
- [MCP Server Setup](mcp-setup.md) — manual setup for AI tools (usually not needed after `dotscope init`)
- [CLI Reference](cli-reference.md) — every command dotscope offers
- [Architecture](architecture.md) — how dotscope itself is built (for contributors)
