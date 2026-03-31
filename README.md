<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

Every agent that touches your code starts from zero. It doesn't know
which files depend on each other. It doesn't know your naming conventions.
It doesn't know that changing a Django model will break an Angular
component on the other side of the repo. It just writes code, commits,
and moves on. You find out at 2 AM.

Now scale that to five agents working at once.

**dotscope is the operating system for your codebase.** It sits between
your agents and your code. It remembers the architecture so they don't
have to.

It does four things:

1. **Enforces contracts across languages.** Your Python backend and
   TypeScript frontend share an invisible API contract. dotscope sees
   both sides. Change a Django ViewSet without updating the Angular
   component that calls it? Blocked. It extracts routes from FastAPI,
   Flask, and DRF. It extracts fetch calls from React and Angular.
   It links them automatically.

2. **Routes files to the right place.** Before an agent creates a file,
   it asks dotscope where it should go. dotscope reads the dependency
   graph and routes the file to the directory where it belongs. If an
   agent ignores the routing, the commit gets a fix with `git mv` and
   AST-safe import rewrites already generated.

3. **Coordinates multiple agents.** When Agent A starts working on
   billing, dotscope locks the blast radius — the files billing depends
   on, the tests that cover it, the frontend components that consume it.
   Agent B can work on auth at the same time without collision. If they
   touch the same file, the AST merge driver resolves it semantically
   instead of with line-level conflict markers.

4. **Teaches the style.** Your codebase has conventions. dotscope
   discovers them from your code and your git history, then holds every
   agent to the same standard.

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
