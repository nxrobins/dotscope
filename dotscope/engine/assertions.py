"""Architectural assertions: compiler-grade guarantees on scope resolution.

Assertions prevent silent context corruption. If a critical file gets
dropped by token budgeting, dotscope raises an error instead of serving
incomplete context.

Defined in intent.yaml (project-wide) or .scope files (per-scope).
"""

from typing import Dict, List, Optional

from ..models.intent import Assertion, ContextExhaustionError  # noqa: F401
from ..ux.textio import read_repo_text


def load_assertions(repo_root: str, scope_name: str = "") -> List[Assertion]:
    """Load assertions from intent.yaml and the scope's .scope file.

    Args:
        repo_root: Repository root
        scope_name: Current scope being resolved (for per-scope assertions)
    """
    import os
    assertions = []

    # 1. Project-wide assertions from intent.yaml
    intent_path = os.path.join(repo_root, "intent.yaml")
    if os.path.exists(intent_path):
        from ..engine.parser import _parse_yaml
        data = _parse_yaml(read_repo_text(intent_path).text)
        for item in _to_list_of_dicts(data.get("assertions", [])):
            assertions.append(_parse_assertion(item))

    # 2. Per-scope assertions from .scope file
    if scope_name:
        from ..engine.discovery import find_scope
        scope_path = find_scope(scope_name, repo_root)
        if scope_path:
            try:
                from ..engine.parser import _parse_yaml
                data = _parse_yaml(read_repo_text(scope_path).text)
                raw = data.get("assertions", {})
                if isinstance(raw, dict):
                    a = Assertion(scope=scope_name)
                    a.ensure_includes = _str_list(raw.get("ensure_includes", []))
                    a.ensure_context_contains = _str_list(raw.get("ensure_context_contains", []))
                    a.ensure_constraints = bool(raw.get("ensure_constraints", False))
                    if a.ensure_includes or a.ensure_context_contains or a.ensure_constraints:
                        assertions.append(a)
            except Exception:
                pass

    return assertions


def get_required_files(
    assertions: List[Assertion],
    scope_name: str,
) -> set:
    """Return set of files that must be included (infinite utility)."""
    required = set()
    for a in assertions:
        if a.scope == "*" or a.scope == scope_name:
            required.update(a.ensure_includes)
    return required


def check_output_assertions(
    resolved_context: str,
    constraints: list,
    assertions: List[Assertion],
    scope_name: str,
) -> Optional[ContextExhaustionError]:
    """Check non-file assertions against resolved output."""
    for a in assertions:
        if a.scope != "*" and a.scope != scope_name:
            continue

        if a.ensure_context_contains:
            for substring in a.ensure_context_contains:
                if substring.lower() not in resolved_context.lower():
                    return ContextExhaustionError(
                        assertion_type="ensure_context_contains",
                        detail=f"Context must contain '{substring}'",
                        reason=a.reason,
                        suggestion=f"Add '{substring}' to scope context or check context truncation",
                    )

        if a.ensure_constraints and not constraints:
            return ContextExhaustionError(
                assertion_type="ensure_constraints",
                detail="Resolve response must include constraints",
                reason=a.reason,
                suggestion="Check that invariants.json and intent.yaml exist",
            )

    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _parse_assertion(item: dict) -> Assertion:
    """Parse a single assertion from intent.yaml."""
    return Assertion(
        scope=str(item.get("scope", "*")),
        ensure_includes=_str_list(item.get("ensure_includes", [])),
        ensure_context_contains=_str_list(item.get("ensure_context_contains", [])),
        ensure_constraints=bool(item.get("ensure_constraints", False)),
        reason=str(item.get("reason", "")),
    )


def _str_list(val: object) -> List[str]:
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str) and val:
        return [v.strip() for v in val.split(",")]
    return []


def _to_list_of_dicts(val: object) -> List[dict]:
    """Handle both parsed lists and raw YAML structures."""
    if isinstance(val, list):
        return [v for v in val if isinstance(v, dict)]
    return []
