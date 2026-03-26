"""Scope composition algebra.

Supports expressions like:
    auth+payments     — merge (union of files, concatenate context)
    auth-tests        — subtract (remove files matching subtracted scope)
    auth&api          — intersect (only files in both)
    auth@context      — modifier (context only, no files)

Operators bind left-to-right, no precedence. @ is a suffix modifier.
"""


import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .discovery import find_scope, find_repo_root
from .models import ResolvedScope
from .resolver import resolve
from .tokens import estimate_scope_tokens, estimate_context_tokens


class Op(Enum):
    MERGE = "+"
    SUBTRACT = "-"
    INTERSECT = "&"


@dataclass
class ScopeRef:
    """A reference to a scope with optional modifier."""
    name: str
    context_only: bool = False


@dataclass
class ScopeOp:
    """An operation in a scope expression."""
    operator: Optional[Op]  # None for the first operand
    ref: ScopeRef


def parse_expression(expr: str) -> List[ScopeOp]:
    """Parse a scope expression into a list of operations.

    Examples:
        "auth"              → [ScopeOp(None, ScopeRef("auth"))]
        "auth+payments"     → [ScopeOp(None, "auth"), ScopeOp(MERGE, "payments")]
        "auth-tests"        → [ScopeOp(None, "auth"), ScopeOp(SUBTRACT, "tests")]
        "auth@context"      → [ScopeOp(None, ScopeRef("auth", context_only=True))]
    """
    expr = expr.strip()
    if not expr:
        raise ValueError("Empty scope expression")

    # Tokenize on operators, keeping the operators
    tokens = re.split(r"([+\-&])", expr)
    tokens = [t.strip() for t in tokens if t.strip()]

    ops: List[ScopeOp] = []
    current_op: Optional[Op] = None

    for token in tokens:
        if token in ("+", "-", "&"):
            current_op = Op(token)
        else:
            ref = _parse_ref(token)
            ops.append(ScopeOp(operator=current_op, ref=ref))
            current_op = None

    if not ops:
        raise ValueError(f"Invalid scope expression: {expr}")

    return ops


def _parse_ref(token: str) -> ScopeRef:
    """Parse a scope reference, handling @modifier."""
    if "@" in token:
        name, modifier = token.split("@", 1)
        if modifier == "context":
            return ScopeRef(name=name, context_only=True)
        else:
            raise ValueError(f"Unknown modifier @{modifier}. Supported: @context")
    return ScopeRef(name=token)


def compose(
    expr: str,
    root: Optional[str] = None,
    follow_related: bool = True,
) -> ResolvedScope:
    """Resolve a scope expression to a ResolvedScope.

    This is the main entry point for scope composition.
    """
    if root is None:
        root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root. No .scopes, .git, or .scope found.")

    ops = parse_expression(expr)
    result: Optional[ResolvedScope] = None

    for op in ops:
        # Resolve the scope reference
        config = find_scope(op.ref.name, root)
        if config is None:
            # Lazy ingest: generate scope on demand
            from .passes.lazy import lazy_ingest_module
            config = lazy_ingest_module(root, op.ref.name)
            if config is None:
                raise ValueError(f"Scope not found: {op.ref.name}")

        resolved = resolve(config, follow_related=follow_related, root=root)

        # Apply @context modifier
        if op.ref.context_only:
            resolved = ResolvedScope(
                files=[],
                context=resolved.context,
                token_estimate=estimate_context_tokens(resolved.context),
                scope_chain=resolved.scope_chain,
                truncated=False,
            )

        # Apply operator
        if result is None:
            result = resolved
        elif op.operator == Op.MERGE:
            result = result.merge(resolved)
        elif op.operator == Op.SUBTRACT:
            result = result.subtract(resolved)
            # Recalculate tokens after subtraction
            result.token_estimate = (
                estimate_scope_tokens(result.files)
                + estimate_context_tokens(result.context)
            )
        elif op.operator == Op.INTERSECT:
            result = result.intersect(resolved)
            result.token_estimate = (
                estimate_scope_tokens(result.files)
                + estimate_context_tokens(result.context)
            )

    return result or ResolvedScope()
