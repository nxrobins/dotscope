<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

You give an agent a task. It searches your codebase, finds the files,
writes the code, runs the tests, and ships. Sounds fine until you
realize it changed a backend endpoint without touching the frontend
that calls it. It put a utility function in `src/helpers/` instead of
next to the module that uses it. It ignored the naming convention every
other file follows. And when two agents worked at the same time, they
silently overwrote each other's changes.

The code compiled. The tests passed. Production broke.

This happens because agents don't have what you have — the full
picture. They see files. You see architecture.

**dotscope is the operating system for agent-driven codebases.**

One command scans your project and learns the architecture: which files
depend on which, what patterns your code follows, how your backend
talks to your frontend, and what breaks when something changes. From
that point on, every agent gets the full picture before it writes a
line.

It does five things:

1. **One search, everything you need.** An agent describes what it
   wants to do. dotscope returns the relevant files, the functions
   they call, the contracts they must honor, the conventions they must
   follow, and which files are locked by other agents. One call. Not
   five.

2. **Enforces contracts across languages.** Your Python backend and
   TypeScript frontend share an invisible API contract. dotscope
   extracts routes from FastAPI, Flask, and DRF. It extracts fetch
   calls from React and Angular. It links them automatically. Change
   a Django ViewSet without updating the Angular component? Blocked.

3. **Routes files to the right place.** Before an agent creates a
   file, it asks dotscope where it should go. dotscope reads the
   dependency graph and routes the file there. No more `src/utils/`
   graveyards.

4. **Coordinates multiple agents.** When Agent A starts working on
   billing, dotscope locks the blast radius. Agent B works on auth
   without collision. If they touch the same function, the AST merge
   driver resolves it semantically — not with conflict markers.

5. **Gets smarter with every commit.** Which search results did agents
   actually use? Which did they ignore? dotscope tracks this and
   adjusts. Conventions that hold up get enforced harder. Rules that
   get overridden get quieter.

Here's what it looks like on a real codebase:

```
$ dotscope ingest

  Analyzing dependency graph...
  Mining git history...
  Discovering conventions...

  Discoveries:
  - version.py and environment.prod.ts always change together
  - workflow-edit-dialog.component.ts and models.py are tightly coupled

  Validation (49 commits backtested):
  - Overall recall: 78%
  - Token reduction: 67% (1.3M → 437K avg)

  Output: 3 .scope files written.

$ dotscope check --backtest

  13 issues flagged across 7 commits:
  - models.py changes need the Angular component updated
  - consumer.py changes need matching parser test updates
  - views.py changes typically need test_api_search.py updated

  3 commits were clean.
```

One command. Point it at anything.

```
pip install dotscope && dotscope init
```

[How It Works](docs/how-it-works.md) · [Scope Files](docs/scope-file.md) · [Agent Instructions](AGENT_INSTRUCTIONS.md) · [MIT](LICENSE)
