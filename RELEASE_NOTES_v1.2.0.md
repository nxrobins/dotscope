# dotscope v1.2.0 - The Compiled Codebase

## What's New

dotscope 1.2 transforms from a context compiler into a full codebase compiler. Agents still get `.scope` files, but now they see the architecture that wasn't there before.

### 🔗 Cross-Language Contract Detection
Your Python backend and TypeScript frontend share invisible API contracts. dotscope now extracts routes from FastAPI/Flask/DRF and links them to fetch/axios calls in React/Angular. Change a Django ViewSet without updating the Angular component that consumes it? Blocked.

### 🏗️ Convention Discovery
Every codebase has patterns nobody documented. dotscope discovers them from structure and enforces them at the strength your codebase actually exhibits. 92% compliance = blocking. 65% = suggestion. Below 50% = retired.

### 🤝 Multi-Agent Coordination
Swarm locks with depth-dampened blast radius. When Agent A works on billing, dotscope locks the architectural neighborhood. Agent B can work on auth without collision. If they touch the same file, the AST merge driver resolves it semantically.

### 📊 Generated Architecture Docs
Three commands, three files:
```bash
dotscope init && dotscope ingest && dotscope generate
```

- `ARCHITECTURE_CONTRACTS.md` — rules nobody wrote down
- `NETWORK_MAP.md` — cross-language endpoint topology  
- `CO_CHANGE_ATLAS.md` — structural coupling invisible in the import graph

### 🧠 Self-Improving Feedback Loop
Which files do agents actually use? Which do they ignore? dotscope tracks this and adjusts. Recall improves from ~78% to 91%+ with use.

## Breaking Changes
None. All v1.0 workflows continue to work.

## Technical Details
- 423 tests across 7 analysis pillars
- Zero dependencies (Python 3.10+ stdlib only)
- New tree-sitter parsers for polyglot analysis
- Custom AST merge driver for semantic conflict resolution
- Empirical architecture derived from git history

---

Full technical writeup: [The Compiled Codebase](https://nigelxavier.substack.com/p/the-compiled-codebase)