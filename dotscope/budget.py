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
) -> ResolvedScope:
    """Apply a token budget to a resolved scope.

    Algorithm:
    1. Reserve tokens for context (always included)
    2. Rank files by relevance tier and size
    3. Fill files until budget is exhausted
    4. Set truncated=True if files were dropped

    Args:
        resolved: The fully resolved scope
        max_tokens: Maximum total tokens (context + files)
        task: Optional task description for relevance ranking
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

    # Rank and score files
    scored_files = _rank_files(resolved.files, task)

    # Fill within budget
    selected_files: List[str] = []
    total_file_tokens = 0

    for path, _score in scored_files:
        file_tokens = estimate_file_tokens(path)
        if total_file_tokens + file_tokens <= remaining:
            selected_files.append(path)
            total_file_tokens += file_tokens
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
) -> List[tuple]:
    """Rank files by relevance. Returns list of (path, score).

    Ranking heuristics:
    - Smaller files score higher (more focused, less noise)
    - If task is provided, files with task keywords in their name score higher
    - Core source files score higher than test/config files
    """
    import os

    task_words = set()
    if task:
        task_words = {w.lower() for w in task.split() if len(w) > 2}

    scored = []
    for path in files:
        score = 1.0
        basename = os.path.basename(path).lower()
        rel_parts = path.lower().split(os.sep)

        # Penalize test/fixture/migration files
        if any(p in ("tests", "test", "fixtures", "migrations", "__pycache__") for p in rel_parts):
            score *= 0.5

        # Penalize config/generated files
        if basename.endswith((".generated.py", ".generated.ts", ".lock", ".min.js")):
            score *= 0.3

        # Boost files matching task keywords
        if task_words:
            name_words = set(
                w for w in basename.replace("_", " ").replace("-", " ").replace(".", " ").split()
                if len(w) > 2
            )
            overlap = len(task_words & name_words)
            if overlap:
                score *= 1.0 + (overlap * 0.5)

        # Prefer smaller files (less noise)
        tokens = estimate_file_tokens(path)
        if tokens > 0:
            # Files under 200 tokens get a boost, very large files get penalized
            if tokens < 200:
                score *= 1.2
            elif tokens > 2000:
                score *= 0.8

        scored.append((path, score, tokens))

    # Sort by score descending, then by token count ascending (prefer small files at same score)
    scored.sort(key=lambda x: (-x[1], x[2]))
    return [(path, score) for path, score, _ in scored]
