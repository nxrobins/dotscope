# dotscope Agent Instructions

## How This Codebase Works

This repository is managed by dotscope, a codebase compiler that provides you with architectural context, dependency analysis, and mutation safety. You have access to dotscope's FastMCP tools natively. Use them instead of manually reading files and guessing at architecture.

## The One Rule

**Start every task by mapping scopes.** Do not read files manually. Do not guess which files are relevant. Tools like `match_scope` and `resolve_scope` return the code, its dependency neighborhood, the bodies of functions it calls, the contracts you must honor, the conventions you must follow, and which files another agent is currently mutating. One call replaces dozens of terminal commands.

```
# Wrong: manual discovery
1. Read src/billing/webhooks.py
2. Read src/billing/processor.py
3. Read tests/billing/test_webhooks.py
4. Guess at conventions
5. Hope nothing is locked

# Right: compiled retrieval
1. mcp_dotscope_resolve_scope(scope="billing")
   → code + dependencies + abstractions + contracts + locks — done
```

---

## Tool Reference

### Discovery

**`mcp_dotscope_match_scope(task)`**
When you don't know the exact scope name, use this search block. It matches your natural language intent against index tags and keywords to return a ranked list of relevant scope identifiers string formats with confidence values.

**`mcp_dotscope_resolve_scope(scope_name, task?, budget?, follow_related?)`**
Your primary entry point once a scope name is identified (e.g. "billing" or "auth").
Returns a JSON-compiled `ResolvedScope`:
- `files` — ranked by architectural relevance, budget-fitted. Trust the ranking.
- `context` — the unwritten rules, invariants, and architectural metadata.
- `constraints` — implicit contracts, anti-patterns, intents you must respect.

**`mcp_dotscope_get_context(scope, section?)`**
Used when you explicitly just want to evaluate the context invariants of the scope without fetching actual script sources to preserve token boundaries.

---

### Verification and Safety

**`mcp_dotscope_claim_scope(agent_id, task_description, primary_files)`**
Claim exclusive write access before modifying files. The claim includes an automatically calculated blast radius: direct dependents get exclusive locks, two-hop dependents get shared locks. Other agents can still read but will be warned before claiming overlapping files. 
Call this AFTER `resolve_scope` but BEFORE writing any code.

**`mcp_dotscope_renew_lock(lock_id)`**
If your task is taking longer than expected and your lock expires, renew it immediately.

**`mcp_dotscope_check(diff?, explain?)`**
Pre-commit verification. Runs your changes against the structural bounds: implicit contracts, network contracts, convention compliance, co-change requirements. This is your safety net. Always run it before committing.

**`mcp_dotscope_escalate(conflict_id)`**
When you're stuck in a conflict you can't resolve: interlocking locks, merge conflicts, contract violations that require cross-scope changes beyond your claim.

**`mcp_dotscope_scope_health()`**
Provides a diagnostic overlay mapping reporting on ecosystem staleness, file coverage, and dependency import drift. Check this if validation tests suddenly fail.

---

## Reading a `resolve_scope` Response

The response format relies heavily on architectural metadata:

**`files`** — These are the files you'll be working in. They're ranked by relevance inside the `.scope` bounds.

**`context`** — Read the invariants to understand the interface contracts. Check your abstractions explicitly against the stated gotchas.

**`constraints`** — These are the rules. If a constraint says "when `pricing_engine.py` changes, `tax_calculator.py` must also change," then you must change both or change neither. Constraints with `severity: "GUARD"` will block your commit if violated. 

**`action_hints`** — Fast directives guiding exactly how you should initialize your changes inside the scope files.

---

## Standard Workflow

### For any code modification task:

```
1. DISCOVER    mcp_dotscope_match_scope("your task description") -> "billing"
2. RESOLVE     mcp_dotscope_resolve_scope("billing")
3. CLAIM       mcp_dotscope_claim_scope("agent-123", "task description", [...])
4. WRITE       Make your changes, respecting constraints and conventions
5. CHECK       mcp_dotscope_check(your_diff)
6. FIX         If violations, fix and re-check
7. COMMIT      Only after check passes
```

### For multi-file changes:
If `resolve_scope` returns a **co-change contract** (e.g., `pricing_engine.py` ↔ `tax_calculator.py`), you must modify both files in the same commit. Changing one without the other breaks historical Git dependencies!

### For cross-scope work:
Claim each scope explicitly using `+` algebra if necessary (`mcp_dotscope_resolve_scope("auth+payments")`). Do not modify files outside your claimed bounds.

---

## Anti-Patterns

**Do not manually crawl the repo.** Every `view_file` call you make instead of using `mcp_dotscope_resolve_scope` breaks boundaries mapping and wastes token contexts. Dotscope has already read the files, resolved the dependencies, and applied exclusions natively.

**Do not ignore GUARD constraints.** `mcp_dotscope_check` will definitively reject your structural alignments if violated. Fix the violation rather than working around it.

**Do not guess at file connections.** If you modify a file, use dotscope to map its dependencies and test its downstream consequences.
