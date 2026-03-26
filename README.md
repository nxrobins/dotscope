<p align="center">
  <img src="logo.png" alt="dotscope" width="400">
</p>

```
pip install dotscope && dotscope init
```

Your agents now understand your codebase's architecture, conventions, and coding style.

What changed:

- Agent knows which files always change together (from your git history)
- Agent follows your team's structural conventions automatically
- Agent matches your codebase's type hint density and docstring style
- Frozen modules can't be modified. Deprecated code can't be imported.
- Every commit makes it smarter.

```
  12 scopes, 4 contracts, 3 conventions, 91% recall

  What dotscope would have caught in your last 50 commits:
    7 files that agents would have missed

  Your agents are ready.
```

## Docs

- [How It Works](docs/how-it-works.md)
- [The .scope File](docs/scope-file.md)
- [MCP Server Setup](docs/mcp-setup.md)
- [CLI Reference](docs/cli-reference.md)
- [Architecture](docs/architecture.md)

## Details

Python 3.9+. One dependency ([tree-sitter](https://tree-sitter.github.io/)). Cross-platform. Python, JavaScript, TypeScript, Go. 348 tests. [MIT](LICENSE).
