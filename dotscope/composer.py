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

from .discovery import find_repo_root, find_resolution_scope
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
        config = find_resolution_scope(op.ref.name, root)
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


def compose_for_task(
    task: str,
    root: Optional[str] = None,
    max_scopes: int = 3,
    threshold: float = 0.05,
) -> ResolvedScope:
    """Auto-compose scopes by matching a task description.

    Discovers all scopes, ranks them by task relevance, and merges
    the top N into a single ResolvedScope using the + operator.

    Args:
        task: Natural language task description.
        root: Repository root (auto-detected if None).
        max_scopes: Maximum scopes to compose (default 3).
        threshold: Minimum match score to include a scope.

    Returns:
        Composed ResolvedScope, or empty if no scopes match.
    """
    import os
    from .discovery import find_all_scopes
    from .matcher import match_task
    from .parser import parse_scope_file

    if root is None:
        root = find_repo_root()
    if root is None:
        return ResolvedScope()

    scope_files = find_all_scopes(root)
    if not scope_files:
        return ResolvedScope()

    # Build (name, keywords, description) tuples for the matcher
    # Enrich keywords with scope name and include path components
    scope_tuples = []
    seen_names = set()
    for sf in scope_files:
        try:
            config = parse_scope_file(sf)
            name = os.path.basename(os.path.dirname(config.path)) or "root"
            if name not in seen_names:
                keywords = list(config.tags)
                # Add scope name and include path components as keywords
                keywords.append(name)
                for inc in config.includes:
                    for part in inc.replace("/", " ").replace("_", " ").replace("-", " ").split():
                        if len(part) > 2 and part not in keywords:
                            keywords.append(part.lower())
                scope_tuples.append((name, keywords, config.description))
                seen_names.add(name)
        except Exception:
            continue

    if not scope_tuples:
        return ResolvedScope()

    matches = match_task(task, scope_tuples, threshold)
    if not matches:
        return ResolvedScope()

    # Resolve each matched scope and tag files with match score
    top_matches = matches[:max_scopes]
    result: Optional[ResolvedScope] = None

    for name, score in top_matches:
        config = find_resolution_scope(name, root)
        if config is None:
            continue
        resolved = resolve(config, follow_related=True, root=root)
        # Tag each file with the scope's match score
        resolved.file_scores = {f: score for f in resolved.files}

        if result is None:
            result = resolved
        else:
            result = result.merge(resolved)

    return result or ResolvedScope()
