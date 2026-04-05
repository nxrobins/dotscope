import json
import os
from typing import Optional

def register_observability_tools(mcp, **kwargs):
    tracker = kwargs.get('tracker')
    client_id = kwargs.get('client_id')
    _root = kwargs.get('_root')
    _repo_tokens = kwargs.get('_repo_tokens')
    _cached_history = kwargs.get('_cached_history')
    _cached_graph_hubs = kwargs.get('_cached_graph_hubs')
    _cli_root = kwargs.get('_cli_root')

    @mcp.tool()
    def validate_scopes() -> str:
        """Validate all .scope files for broken paths and common issues.

        Checks:
        - Include paths exist
        - Related scope files exist
        - Description is not empty
        - Context field is present (the most valuable part)
        """
        from ..paths.repo import find_repo_root
        from ..discovery import find_all_scopes
        from ..parser import parse_scope_file

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
        from ..health import full_health_report
        from ..paths.repo import find_repo_root
        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        report = full_health_report(root, use_runtime=True)
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
    def dotscope_refresh(
        scopes: Optional[list[str]] = None,
        repo: bool = False,
    ) -> str:
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
        from ..paths.repo import find_repo_root
        from ..refresh import run_refresh_inline

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        result = run_refresh_inline(
            root,
            targets=scopes if scopes and not repo else None,
            repo=repo or not scopes,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    def dotscope_check(
        diff: Optional[str] = None,
        session_id: Optional[str] = None,
        explain: bool = False,
    ) -> str:
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
        from ..paths.repo import find_repo_root

        root = find_repo_root()
        if root is None:
            return json.dumps({"error": "Could not find repository root"})

        if diff:
            report = check_diff(diff, root, session_id=session_id)
        else:
            report = check_staged(root, session_id=session_id)

        explain_fn = None
        if explain:
            from ..explain import explain_warning
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

        return json.dumps({
            "passed": report.passed,
            "guards": [_fmt_result(r) for r in report.guards],
            "nudges": [_fmt_result(r) for r in report.nudges],
            "notes": [_fmt_result(r) for r in report.notes],
            "holds": [_fmt_result(r) for r in report.guards],  # backwards compat
            "files_checked": report.files_checked,
        }, indent=2)
