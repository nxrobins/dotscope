<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

Your agent writes code that compiles, passes tests, and breaks production.

It changed a backend endpoint without touching the frontend that calls it.
It put a file in `src/helpers/` instead of next to the module that uses it.
It ignored the convention every other file follows. Two agents working at
the same time silently overwrote each other.

The agent sees files. You see architecture. dotscope closes that gap.

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
```

One MCP tool call. The agent gets the relevant code, its dependency
neighborhood, implicit contracts from git history, convention rules,
swarm lock status, and action hints. One call, not five.

dotscope learns from every commit. Files agents consistently need get
ranked higher. Conventions that hold get enforced harder. Rules that
get overridden get quieter. Recall starts at 78% and climbs past 91%.

```
pip install dotscope && dotscope init
```

Zero dependencies. Python 3.9+ stdlib only. MIT.

[How It Works](docs/how-it-works.md) · [Scope Files](docs/scope-file.md) · [Agent Instructions](AGENT_INSTRUCTIONS.md) · [MIT](LICENSE)
