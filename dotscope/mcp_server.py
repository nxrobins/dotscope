"""MCP server for dotscope — the primary agent-facing interface.

Exposes scope resolution, matching, and context as MCP tools
that any MCP-compatible agent can call.

Install: pip install dotscope[mcp]
Run: dotscope-mcp (stdio transport)

Configure in Claude Desktop or similar:
{
    "mcpServers": {
        "dotscope": {
            "command": "dotscope-mcp"
        }
    }
}
"""


import json
import os
import sys


def main():
    """MCP server entry point."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP server requires the 'mcp' package.\n"
            "Install with: pip install dotscope[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp = FastMCP(
        "dotscope",
        description=(
            "Directory-scoped context boundaries for AI coding agents. "
            "Resolve .scope files to curated file lists with architectural context."
        ),
    )

    @mcp.tool()
    def resolve_scope(
        scope: str,
        budget: int | None = None,
        follow_related: bool = True,
        format: str = "json",
    ) -> str:
        """Resolve a scope expression to a file list with architectural context.

        Scope expressions support composition:
        - "auth" — single scope
        - "auth+payments" — merge two scopes (union of files)
        - "auth-tests" — subtract (auth files minus test scope files)
        - "auth&api" — intersect (only files in both)
        - "auth@context" — context only, no files

        If budget is set, returns the most relevant files fitting within
        that token count. Context is always included first, then files are
        ranked by relevance and loaded until the budget is exhausted.

        Args:
            scope: Scope name, path, or composition expression
            budget: Max tokens for context + files (None = no limit)
            follow_related: Whether to follow related scope references
            format: Output format — "json", "plain", or "cursor"
        """
        from .composer import compose
        from .budget import apply_budget
        from .discovery import find_repo_root
        from .formatter import format_resolved

        root = find_repo_root()
        resolved = compose(scope, root=root, follow_related=follow_related)

        if budget is not None:
            resolved = apply_budget(resolved, budget)

        # Track session (MCP calls only — compose stays pure)
        session_id = None
        try:
            from .sessions import SessionManager
            mgr = SessionManager(root)
            mgr.ensure_initialized()
            task_str = f"resolve {scope}" + (f" (budget={budget})" if budget else "")
            session_id = mgr.create_session(scope, task_str, resolved.files, resolved.context)
            resolved.context = f"# dotscope-session: {session_id}\n{resolved.context}"
        except Exception:
            pass  # Session tracking failures never block resolution

        return format_resolved(resolved, fmt=format, root=root)

    @mcp.tool()
    def match_scope(task: str) -> str:
        """Find the most relevant scope(s) for a task description.

        Uses keyword overlap between the task and scope keywords/tags/descriptions.
        Returns a ranked list with confidence scores.

        Args:
            task: Natural language description of what you're working on
        """
        from .discovery import find_repo_root, load_index, find_all_scopes
        from .matcher import match_task
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        index = load_index(root)
        scope_files = find_all_scopes(root)

        scopes = []
        if index:
            for name, entry in index.scopes.items():
                scopes.append((name, entry.keywords, entry.description or ""))
        else:
            for sf in scope_files:
                try:
                    config = parse_scope_file(sf)
                    name = os.path.relpath(os.path.dirname(sf), root)
                    scopes.append((name, config.tags, config.description))
                except (ValueError, IOError):
                    continue

        matches = match_task(task, scopes)

        return json.dumps({
            "matches": [
                {"scope": name, "confidence": round(score, 3)}
                for name, score in matches
            ],
            "task": task,
        }, indent=2)

    @mcp.tool()
    def get_context(scope: str, section: str | None = None) -> str:
        """Get architectural context for a scope without loading any files.

        This is the knowledge that isn't in the code itself: invariants,
        gotchas, conventions, architectural decisions.

        Args:
            scope: Scope name or path
            section: Optional section name to filter (e.g., "invariants", "gotchas")
        """
        from .discovery import find_scope, find_repo_root
        from .context import query_context

        root = find_repo_root()
        config = find_scope(scope, root)
        if config is None:
            return json.dumps({"error": f"Scope not found: {scope}"})

        result = query_context(config.context, section)
        return json.dumps({
            "scope": scope,
            "section": section,
            "context": result,
            "description": config.description,
        }, indent=2)

    @mcp.tool()
    def list_scopes() -> str:
        """List all available scopes with descriptions, tags, and token estimates.

        Searches the .scopes index and/or walks the directory tree for .scope files.
        """
        from .discovery import find_repo_root, load_index, find_all_scopes
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        scopes = []
        index = load_index(root)

        if index:
            for name, entry in index.scopes.items():
                scopes.append({
                    "name": name,
                    "path": entry.path,
                    "keywords": entry.keywords,
                    "description": entry.description,
                })
        else:
            for sf in find_all_scopes(root):
                try:
                    config = parse_scope_file(sf)
                    scopes.append({
                        "name": os.path.relpath(os.path.dirname(sf), root),
                        "path": os.path.relpath(sf, root),
                        "tags": config.tags,
                        "description": config.description,
                        "tokens_estimate": config.tokens_estimate,
                    })
                except (ValueError, IOError):
                    continue

        return json.dumps({"scopes": scopes, "count": len(scopes)}, indent=2)

    @mcp.tool()
    def validate_scopes() -> str:
        """Validate all .scope files for broken paths and common issues.

        Checks:
        - Include paths exist
        - Related scope files exist
        - Description is not empty
        - Context field is present (the most valuable part)
        """
        from .discovery import find_repo_root, find_all_scopes
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        issues = []
        for sf in find_all_scopes(root):
            rel = os.path.relpath(sf, root)
            try:
                config = parse_scope_file(sf)
            except ValueError as e:
                issues.append({"scope": rel, "severity": "error", "message": str(e)})
                continue

            for inc in config.includes:
                full = os.path.normpath(os.path.join(root, inc))
                if not os.path.exists(full.rstrip("/")):
                    issues.append({
                        "scope": rel, "severity": "error",
                        "message": f"include path not found: {inc}",
                    })

            if not config.context_str.strip():
                issues.append({
                    "scope": rel, "severity": "warning",
                    "message": "no context — this is the most valuable part",
                })

        return json.dumps({"issues": issues, "count": len(issues)}, indent=2)

    @mcp.tool()
    def scope_health() -> str:
        """Report on scope health: staleness, coverage gaps, and import drift.

        Staleness: files changed since .scope was last modified
        Coverage: directories with no .scope file
        Drift: imports in scoped files that aren't in the includes list
        """
        from .health import full_health_report
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        report = full_health_report(root)
        return json.dumps({
            "scopes_checked": report.scopes_checked,
            "coverage_pct": round(report.coverage_pct, 1),
            "directories_covered": report.directories_covered,
            "directories_total": report.directories_total,
            "issues": [
                {
                    "scope": i.scope_path,
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                }
                for i in report.issues
            ],
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
        }, indent=2)

    @mcp.tool()
    def ingest_codebase(
        directory: str = ".",
        mine_history: bool = True,
        absorb_docs: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Reverse-engineer .scope files from an existing codebase.

        Analyzes the dependency graph, mines git history, and absorbs existing
        documentation to produce complete .scope files for every detected module.

        This is how dotscope enters any codebase — no manual .scope writing needed.

        Args:
            directory: Repository root to ingest (default: current directory)
            mine_history: Whether to analyze git history for change patterns
            absorb_docs: Whether to scan for README, docstrings, signal comments
            dry_run: If True, return the plan without writing files
        """
        from .ingest import ingest

        root = os.path.abspath(directory)
        plan = ingest(
            root,
            mine_history=mine_history,
            absorb=absorb_docs,
            dry_run=dry_run,
        )

        return json.dumps({
            "scopes_planned": len(plan.scopes),
            "scopes": [
                {
                    "directory": ps.directory,
                    "description": ps.config.description,
                    "confidence": round(ps.confidence, 3),
                    "includes_count": len(ps.config.includes),
                    "token_estimate": ps.config.tokens_estimate,
                    "signals": ps.signals,
                    "has_context": bool(ps.config.context_str.strip()),
                }
                for ps in plan.scopes
            ],
            "dry_run": dry_run,
            "graph_summary": plan.graph_summary,
        }, indent=2)

    @mcp.tool()
    def impact_analysis(file_path: str) -> str:
        """Predict the blast radius of changes to a specific file.

        Returns which files import this file (direct dependents),
        transitive dependents, and which scopes are affected.

        Args:
            file_path: Path to the file to analyze (relative to repo root)
        """
        from .graph import build_graph
        from .discovery import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        graph = build_graph(root)
        target = os.path.relpath(os.path.abspath(file_path), root)
        node = graph.files.get(target)

        if not node:
            return json.dumps({"error": f"File not found in graph: {target}"})

        # Transitive dependents
        transitive = set()
        for direct in node.imported_by:
            dep_node = graph.files.get(direct)
            if dep_node:
                for t in dep_node.imported_by:
                    if t != target:
                        transitive.add(t)

        affected_modules = set()
        for f in list(node.imported_by) + list(transitive):
            parts = f.split("/")
            if len(parts) > 1:
                affected_modules.add(parts[0])

        total = 1 + len(node.imported_by) + len(transitive)
        risk = "low" if total <= 3 else ("medium" if total <= 10 else "high")

        return json.dumps({
            "file": target,
            "imports": node.imports,
            "imported_by": node.imported_by,
            "transitive_dependents": sorted(transitive),
            "affected_modules": sorted(affected_modules),
            "blast_radius": total,
            "risk": risk,
        }, indent=2)

    @mcp.tool()
    def backtest_scopes_tool(commits: int = 50) -> str:
        """Validate existing scopes against git history.

        Replays recent commits and measures whether each scope's includes
        would have covered the files actually changed. Reports recall
        per scope and suggests missing includes.

        Args:
            commits: Number of recent commits to test against
        """
        from .backtest import backtest_scopes as _backtest
        from .discovery import find_repo_root, find_all_scopes
        from .parser import parse_scope_file

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        configs = []
        for sf in find_all_scopes(root):
            try:
                configs.append(parse_scope_file(sf))
            except (ValueError, IOError):
                continue

        if not configs:
            return json.dumps({"error": "No .scope files found"})

        report = _backtest(root, configs, n_commits=commits)
        return json.dumps({
            "total_commits": report.total_commits,
            "overall_recall": report.overall_recall,
            "results": [
                {
                    "scope": r.scope_path,
                    "recall": r.recall,
                    "commits_tested": r.total_commits,
                    "fully_covered": r.fully_covered,
                    "missing_includes": [
                        {"path": m.path, "appearances": m.appearances}
                        for m in r.missing_includes
                    ],
                }
                for r in report.results
            ],
        }, indent=2)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
