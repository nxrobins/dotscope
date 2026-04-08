<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

# The Hardware-Accelerated Architectural Compiler

Your agent writes code that compiles, passes tests, and breaks production.
The agent sees files. You see architecture. **dotscope closes that gap.**

### N-Body Physics in your Browser
See your codebase's exact structural limits mapped securely across an interactive hardware-accelerated WebGPU rendering engine. Zero browser dependencies. Pure mathematical execution.

![Topography Visualization Physics Placeholder](demo.webp)

```bash
pip install dotscope
dotscope serve
```

---

### The CLI Compiler
dotscope also operates natively in your terminal, acting as the ultimate boundary enforcer natively hooking into MCP.

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
