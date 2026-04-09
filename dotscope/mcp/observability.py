import os
from typing import Optional
from .middleware import mcp_tool_route

def register_observability_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _root = kwargs.get('_root')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')
    _cli_root = kwargs.get('_cli_root')

    @mcp.tool()
    @mcp_tool_route
    def validate_scopes(root: Optional[str] = None) -> dict:
        """Validate all .scope files for broken paths and common issues.

        Checks:
        - Include paths exist
        - Related scope files exist
        - Description is not empty
        - Context field is present (the most valuable part)
        """
        from ..engine.discovery import find_all_scopes
        from ..engine.parser import parse_scope_file

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

        return {"issues": issues, "count": len(issues)}

    @mcp.tool()
    @mcp_tool_route
    def scope_health(root: Optional[str] = None) -> dict:
        """Report on scope health: staleness, coverage gaps, and import drift.

        Staleness: files changed since .scope was last modified
        Coverage: directories with no .scope file
        Drift: imports in scoped files that aren't in the includes list
        """
        from ..ux.health import full_health_report

        report = full_health_report(root, use_runtime=True)
        return {
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
        }

    @mcp.tool()
    @mcp_tool_route
    def dotscope_refresh(
        scopes: Optional[list[str]] = None,
        repo: bool = False,
        root: Optional[str] = None
    ) -> dict:
        """Run a synchronous scope or repo refresh.

        Refreshes runtime scopes so that resolve, health, and check use
        up-to-date data.  Call this after making structural changes or when
        health reports staleness.

        Args:
            scopes: List of scope names to refresh (e.g. ["auth", "payments"]).
                    If omitted, refreshes the entire repo.
            repo: Force a full repo refresh even when scopes are given.

        Returns JSON with success, kind, targets_refreshed, duration_ms, error.
        """
        from ..workflows.refresh import run_refresh_inline

        result = run_refresh_inline(
            root,
            targets=scopes if scopes and not repo else None,
            repo=repo or not scopes,
        )
        return result

    @mcp.tool()
    @mcp_tool_route
    def dotscope_check(
        diff: Optional[str] = None,
        session_id: Optional[str] = None,
        explain: bool = False,
        root: Optional[str] = None
    ) -> dict:
        """Pre-commit verification. Run this before every commit.

        Checks your changes against: implicit contracts, network contracts,
        convention compliance, co-change requirements, swarm locks, and
        anti-patterns.

        Args:
            diff: Git diff text. If omitted, checks staged changes.
            session_id: Session for boundary checking.
            explain: If true, include full provenance for each finding.

        Returns JSON with passed, guards, nudges, notes.
        """
        from ..passes.sentinel.checker import check_diff, check_staged

        if diff:
            report = check_diff(diff, root, session_id=session_id)
        else:
            report = check_staged(root, session_id=session_id)

        explain_fn = None
        if explain:
            from ..ux.explain import explain_warning
            explain_fn = lambda r: explain_warning(root, r)

        def _fmt_result(r):
            d = {
                "category": r.category.value,
                "severity": r.severity.value,
                "message": r.message,
                "file": r.file,
            }
            if r.suggestion:
                d["suggestion"] = r.suggestion
            if r.acknowledge_id:
                d["acknowledge_id"] = r.acknowledge_id
            if r.proposed_fix:
                d["proposed_fix"] = {
                    "file": r.proposed_fix.file,
                    "reason": r.proposed_fix.reason,
                    "predicted_sections": r.proposed_fix.predicted_sections,
                    "proposed_diff": r.proposed_fix.proposed_diff,
                    "confidence": r.proposed_fix.confidence,
                }
            if explain_fn:
                d["explain"] = explain_fn(r)
            return d

        return {
            "passed": report.passed,
            "guards": [_fmt_result(r) for r in report.guards],
            "nudges": [_fmt_result(r) for r in report.nudges],
            "notes": [_fmt_result(r) for r in report.notes],
            "holds": [_fmt_result(r) for r in report.guards],  # backwards compat
            "files_checked": report.files_checked,
        }

    # -------------------------------------------------------------------
    # Swarm Lock MCP tools
    # -------------------------------------------------------------------

    @mcp.tool()
    @mcp_tool_route
    def dotscope_claim_scope(
        agent_id: str,
        task_description: str,
        primary_files: list,
        root: Optional[str] = None
    ) -> dict:
        """Claim exclusive write access before modifying files.

        Call AFTER codebase_search/resolve_scope, BEFORE writing code.
        The claim computes a blast radius: direct dependents get exclusive
        locks, two-hop dependents get shared locks.

        Args:
            agent_id: Your unique identifier.
            task_description: What you plan to do.
            primary_files: Files you intend to modify.

        Returns JSON with:
        - status: "granted", "warning" (shared overlap), or "rejected" (exclusive overlap).
        - exclusive_files: files no other agent can modify while you hold this lock.
        - shared_files: files with soft warnings for other agents.
        - preflight: advisory warnings about what will likely break.
        """
        from ..merge.swarm import claim_scope

        try:
            from ..storage.cache import load_cached_graph_hubs, load_cached_network_edges
            graph_hubs = load_cached_graph_hubs(root)
            network_edges = load_cached_network_edges(root)
        except Exception:
            graph_hubs, network_edges = {}, {}

        result = claim_scope(
            repo_root=root,
            agent_id=agent_id,
            task_description=task_description,
            primary_files=primary_files,
            graph_hubs=graph_hubs,
            network_edges=network_edges,
        )
        return result

    @mcp.tool()
    @mcp_tool_route
    def dotscope_renew_lock(
        lock_id: str,
        root: Optional[str] = None
    ) -> dict:
        """Extend an active lock's expiry by 30 minutes.

        Args:
            lock_id: The lock ID from dotscope_claim_scope.
        """
        from ..merge.swarm import renew_lock

        renewed = renew_lock(root, lock_id)
        return {
            "renewed": renewed,
            "lock_id": lock_id,
            "message": "Lock extended by 30 minutes" if renewed else "Lock not found or expired",
        }

    @mcp.tool()
    @mcp_tool_route
    def dotscope_escalate(
        conflict_id: str,
        root: Optional[str] = None
    ) -> dict:
        """Escalate an unresolvable conflict to a human operator.

        Use when interlocking locks prevent progress or contract violations
        require cross-scope changes beyond your claim.

        Args:
            conflict_id: The conflict ID from a rejected claim.
        """
        from ..merge.swarm import check_escalation

        result = check_escalation(root, conflict_id)
        if result:
            return result
        return {
            "escalation": False,
            "message": "Not yet at escalation threshold. Continue resolution attempts.",
        }
