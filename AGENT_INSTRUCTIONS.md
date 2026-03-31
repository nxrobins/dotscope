# dotscope Agent Instructions

## How This Codebase Works

This repository is managed by dotscope, a codebase compiler that provides you with architectural context, dependency analysis, and mutation safety. You have access to dotscope's MCP tools. Use them instead of manually reading files and guessing at architecture.

## The One Rule

**Start every task with `codebase_search`.** Do not read files manually. Do not guess which files are relevant. `codebase_search` returns the code, its dependency neighborhood, the bodies of functions it calls, the contracts you must honor, the conventions you must follow, and which files another agent is currently mutating. One call replaces five.

```
# Wrong: manual discovery
1. Read src/billing/webhooks.py
2. Read src/billing/processor.py
3. Read tests/billing/test_webhooks.py
4. Guess at conventions
5. Hope nothing is locked

# Right: compiled retrieval
1. codebase_search("Stripe webhook retry logic")
   → code + dependencies + abstractions + contracts + locks — done
```

---

## Tool Reference

### Discovery Tools

**`codebase_search(query, budget?, limit?)`**
Your primary entry point. Natural-language query returns a compiled `ResolvedScope`:
- `files` — ranked by architectural relevance, budget-fitted
- `flattened_abstractions` — bodies of cross-file functions your code calls, with lock status
- `constraints` — implicit contracts, anti-patterns, intents you must respect
- `routing` — convention blueprints, voice rules for how to write new code
- `retrieval_metadata` — index freshness, scores, result count

Use for: any task where you don't already know the scope name.

**`resolve_scope(scope_name, task?)`**
When you already know which scope to work in (e.g., "billing", "auth"). Returns the same `ResolvedScope` structure without the retrieval layer. Useful for follow-up work after an initial `codebase_search`.

Use for: continuing work in a known scope, or when a constraint references a scope by name.

### Mutation Tools

**`dotscope_claim_scope(scope_name, task_description)`**
Claim exclusive write access before modifying files. The claim includes a blast radius: direct dependents get exclusive locks, two-hop dependents get shared locks. Other agents can still read but will be warned before claiming overlapping files.

Call this AFTER `codebase_search` / `resolve_scope` but BEFORE writing any code.

**`dotscope_renew_lock(scope_name)`**
If your task is taking longer than expected and you receive a lock expiry warning in a `resolve_scope` response, renew immediately. An expired lock means another agent can claim your files mid-work.

**`dotscope_check(diff)`**
Pre-commit verification. Runs your changes against the contract enforcement pipeline: implicit contracts, network contracts, convention compliance, co-change requirements. This is your safety net. Always run it before committing.

If `dotscope_check` returns violations, fix them before committing. The violations are structured descriptions — they tell you exactly what broke and why.

**`dotscope_escalate()`**
When you're stuck in a conflict you can't resolve: interlocking locks, merge conflicts, contract violations that require cross-scope changes beyond your claim. Escalation surfaces the full state to a human operator or supervisory agent.

### Documentation Tool

**`generate_artifacts(artifact?)`**
Generates human-readable architecture documents from dotscope's analysis. Useful when asked to "document the architecture" or "explain the system contracts." Produces: `ARCHITECTURE_CONTRACTS.md`, `NETWORK_MAP.md`, `CO_CHANGE_ATLAS.md`.

---

## Reading a `codebase_search` Response

The response is JSON. Here's what to do with each section:

**`files`** — These are the files you'll be working in. They're already ranked by relevance and trimmed to your token budget. Trust the ranking.

**`flattened_abstractions`** — These are the bodies of functions your code calls in other files. Read them to understand the interface contracts. Check `lock_status`:
- `"unlocked"` — safe to modify if needed
- `"shared_locked"` — another agent has nearby work; modify with caution
- `"exclusive_locked"` — another agent owns this; do not modify, work with the current interface

**`constraints`** — These are the rules. If a constraint says "when `pricing_engine.py` changes, `tax_calculator.py` must also change," then you must change both or change neither. Constraints with `severity: "GUARD"` will block your commit if violated. Constraints with `severity: "NOTE"` are advisory.

**`routing`** — These are the conventions. If routing says "all ViewSet classes must include `permission_classes`," your new ViewSet must include it. If it specifies a voice (e.g., "docstrings use imperative mood, max 2 lines"), match it.

**`retrieval_metadata`** — Check `index_freshness`. If it says `"stale"`, the vector index is outdated and results are BM25-only (keyword matching). Execute `dotscope ingest` to rebuild the index before proceeding. Without a fresh index, you are flying blind on conceptual queries.

---

## Standard Workflow

### For any code modification task:

```
1. DISCOVER    codebase_search("your task description")
2. UNDERSTAND  Read the response: files, abstractions, constraints, routing
3. CLAIM       dotscope_claim_scope("scope_name", "task description")
4. WRITE       Make your changes, respecting constraints and conventions
5. CHECK       dotscope_check(your_diff)
6. FIX         If violations, fix and re-check
7. COMMIT      Only after check passes
```

**If step 3 is rejected** (overlapping exclusive locks), do not force the changes. You have three options: wait for the lock to release and retry, switch to a different task that doesn't overlap, or use `dotscope_escalate()` if the blocking lock appears stale or the task is urgent.

### For multi-file changes:

If `codebase_search` returns a co-change contract (e.g., `pricing_engine.py` ↔ `tax_calculator.py`), you must modify both files in the same commit. The contract exists because these files have historically always changed together. Changing one without the other will likely break something.

### For cross-scope work:

If your task requires changes in multiple scopes, claim each scope separately. If a scope is already claimed by another agent, either wait or escalate. Do not modify files outside your claimed scopes.

### When a merge conflict occurs:

If your `git merge` or `git rebase` fails, do NOT look for `<<<<<<< HEAD` markers. dotscope's AST Merge Driver intercepts the failure and injects a `ConflictDescriptor` JSON into your context. This descriptor contains: the conflicting function name, the other agent's version, the dependency footprint of each change, and the relevant architectural contracts. Read the conflict reason, refactor your code to align with the other agent's merged signature, and run `dotscope_check` again. If you cannot resolve the conflict programmatically, use `dotscope_escalate()`.

---

## Anti-Patterns

**Do not manually crawl the repo.** Every `read_file` call you make instead of using `codebase_search` wastes context window and misses architectural signals. `codebase_search` already read the files, resolved the dependencies, flattened the abstractions, and checked the locks.

**Do not ignore constraints.** If a constraint says GUARD severity, `dotscope_check` will reject your commit. Fix the violation rather than working around it.

**Do not skip `dotscope_check`.** It catches contract violations, convention drift, and co-change requirements that are invisible from reading the code alone. A clean diff is not a safe diff.

**Do not modify exclusively-locked files.** If `lock_status` is `"exclusive_locked"`, another agent is actively working on that code. Your changes will conflict. Work with the current interface or escalate.

**Do not guess at conventions.** The `routing` section of the response tells you exactly how to write new code in this scope: naming patterns, import style, docstring format, required attributes. Match them.
