<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

You hire an agent to fix one endpoint. It rewrites the auth module,
ignores the naming convention every other file follows, puts a utility
function in the wrong folder, and breaks a frontend component it didn't
know existed. The code compiles. The tests pass. Production crashes at 2 AM.

This keeps happening because agents don't have what you have — the
full picture. They see files. You see architecture.

**dotscope gives agents the architecture.**

It does three things:

1. **Remembers which files are connected.** Change `billing.py` without
   updating the webhook handler? Blocked. Modify a Django model without
   touching the Angular component that consumes it? Blocked. dotscope
   learns these contracts from your git history and enforces them on
   every commit.

2. **Knows where things go.** Before an agent writes a file, it asks
   dotscope: *"Where should this live?"* dotscope looks at the dependency
   graph, finds the right folder, and routes the file there. No more
   `src/utils/` graveyards.

3. **Teaches the style.** Your codebase has conventions — decorators,
   base classes, naming patterns, import rules. dotscope discovers them
   automatically and holds agents to the same standard your team follows.

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

[How It Works](docs/how-it-works.md) · [Scope Files](docs/scope-file.md) · [MIT](LICENSE)
