"""Token budgeting: rank files, fill to budget, progressive loading.

Context is always included first. Then files are ranked and loaded
until the budget is exhausted.
"""


from typing import List, Optional

from .models import ResolvedScope
from .tokens import estimate_file_tokens, estimate_context_tokens


def apply_budget(
    resolved: ResolvedScope,
    max_tokens: int,
    task: Optional[str] = None,
    utility_scores: Optional[dict] = None,
    required_files: Optional[set] = None,
) -> ResolvedScope:
    """Apply a token budget to a resolved scope.

    Algorithm:
    1. Reserve tokens for context (always included)
    2. Rank files by relevance tier and size, weighted by utility
    3. Fill files until budget is exhausted
    4. Set truncated=True if files were dropped

    Args:
        resolved: The fully resolved scope
        max_tokens: Maximum total tokens (context + files)
        task: Optional task description for relevance ranking
        utility_scores: Historical file utility data from observations
    """
    if max_tokens <= 0:
        return ResolvedScope(
            files=[],
            context=resolved.context,
            token_estimate=estimate_context_tokens(resolved.context),
            scope_chain=resolved.scope_chain,
            truncated=True,
        )

    # Context always goes first
    context_tokens = estimate_context_tokens(resolved.context)
    remaining = max_tokens - context_tokens

    if remaining <= 0:
        # Budget only fits context (or not even that)
        return ResolvedScope(
            files=[],
            context=resolved.context[:max_tokens * 4],  # rough trim
            token_estimate=max_tokens,
            scope_chain=resolved.scope_chain,
            truncated=True,
        )

    # Rank and score files (utility data flows through when available)
    scored_files = _rank_files(resolved.files, task, utility_scores)

    # Required files get infinite utility — selected first, unconditionally
    required = required_files or set()
    if required:
        scored_files = _boost_required(scored_files, required)

    # Fill within budget
    selected_files: List[str] = []
    total_file_tokens = 0

    for path, score in scored_files:
        file_tokens = estimate_file_tokens(path)
        if total_file_tokens + file_tokens <= remaining:
            selected_files.append(path)
            total_file_tokens += file_tokens
        elif path in required:
            # Required file doesn't fit — hard error
            from .assertions import ContextExhaustionError
            raise ContextExhaustionError(
                assertion_type="ensure_includes",
                detail=f"Budget ({max_tokens}) cannot fit required file: {path} ({file_tokens} tokens)",
                file=path,
                file_tokens=file_tokens,
                budget=max_tokens,
                tokens_used=context_tokens + total_file_tokens,
                suggestion=f"Increase budget to at least {context_tokens + total_file_tokens + file_tokens}",
            )
        # Don't break early — a smaller file later might still fit

    truncated = len(selected_files) < len(resolved.files)

    return ResolvedScope(
        files=selected_files,
        context=resolved.context,
        token_estimate=context_tokens + total_file_tokens,
        scope_chain=resolved.scope_chain,
        truncated=truncated,
        excluded_files=[f for f in resolved.files if f not in set(selected_files)],
    )


def _rank_files(
    files: List[str],
    task: Optional[str] = None,
    utility_scores: Optional[dict] = None,
) -> List[tuple]:
    """Rank files by relevance, layering historical utility over static heuristics."""
    import os
    from .utility import effective_score as _effective_score

    task_words = set()
    if task:
        task_words = {w.lower() for w in task.split() if len(w) > 2}

    scored = []
    for path in files:
        score = 1.0
        basename = os.path.basename(path).lower()
        rel_parts = path.lower().split(os.sep)

        if any(p in ("tests", "test", "fixtures", "migrations", "__pycache__") for p in rel_parts):
            score *= 0.5

        if basename.endswith((".generated.py", ".generated.ts", ".lock", ".min.js")):
            score *= 0.3

        if task_words:
            name_words = set(
                w for w in basename.replace("_", " ").replace("-", " ").replace(".", " ").split()
                if len(w) > 2
            )
            overlap = len(task_words & name_words)
            if overlap:
                score *= 1.0 + (overlap * 0.5)

        tokens = estimate_file_tokens(path)
        if tokens > 0:
            if tokens < 200:
                score *= 1.2
            elif tokens > 2000:
                score *= 0.8

        # Layer utility data on top of heuristics
        utility = utility_scores.get(path) if utility_scores else None
        score = _effective_score(score, utility, is_explicit_include=True)

        scored.append((path, score, tokens))

    scored.sort(key=lambda x: (-x[1], x[2]))
    return [(path, score) for path, score, _ in scored]


def _boost_required(
    scored_files: List[tuple],
    required: set,
) -> List[tuple]:
    """Boost required files to infinite utility so they're selected first."""
    boosted = []
    for path, score in scored_files:
        if path in required:
            boosted.append((path, float("inf")))
        else:
            boosted.append((path, score))
    boosted.sort(key=lambda x: -x[1])
    return boosted
