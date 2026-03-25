"""Boundary violation check: agent modified files outside resolved scopes."""

from typing import Dict, List, Optional

from ..models import CheckCategory, CheckResult, Severity


def check_boundaries(
    modified_files: List[str],
    session: Optional[dict],
    scopes: Dict[str, object],
) -> List[CheckResult]:
    """Check if modified files fall outside the session's resolved scopes."""
    if session is None:
        return []  # No session data — skip boundary check

    resolved_files = set(session.get("predicted_files", []))
    if not resolved_files:
        return []

    results = []
    for f in modified_files:
        if f not in resolved_files:
            # Check if it's in ANY scope
            in_scope = any(
                f.startswith(scope_dir + "/") or f.startswith(scope_dir)
                for scope_dir in scopes
            )
            suggestion = (
                "Resolve the relevant scope first"
                if in_scope
                else "This file isn't covered by any scope"
            )
            results.append(CheckResult(
                passed=False,
                category=CheckCategory.BOUNDARY,
                severity=Severity.HOLD,
                message=f"Modified {f} outside resolved scope",
                detail=f"Session resolved: {len(resolved_files)} files, this file was not included",
                file=f,
                suggestion=suggestion,
                can_acknowledge=True,
                acknowledge_id=f"boundary_{f.replace('/', '_').replace('.', '_')}",
            ))

    return results
