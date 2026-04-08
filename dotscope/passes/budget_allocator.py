"""Token budgeting: rank files, fill to budget, progressive loading.

Context is always included first. Then files are ranked and loaded
until the budget is exhausted. Task-type profiles shift budget
allocation between abstractions, network edges, companions, and routing.
"""


from typing import Dict, List, Optional

from ..models import ResolvedScope
from ..engine.tokens import estimate_file_tokens, estimate_context_tokens


# Task-type budget weight profiles
TASK_PROFILES: Dict[Optional[str], Dict[str, float]] = {
    "fix": {
        "primary": 1.0,
        "abstractions": 1.5,    # Understand call chain to find the bug
        "network_edges": 1.0,
        "companions": 0.5,
        "routing": 0.3,
    },
    "add": {
        "primary": 1.0,
        "abstractions": 0.8,
        "network_edges": 1.0,
        "companions": 0.5,
        "routing": 1.5,         # Need conventions to write code that fits
    },
    "refactor": {
        "primary": 1.0,
        "abstractions": 1.2,
        "network_edges": 1.5,   # Refactoring can break consumers
        "companions": 1.2,
        "routing": 0.5,
    },
    "test": {
        "primary": 1.0,
        "abstractions": 1.3,    # Understand what to assert against
        "network_edges": 0.5,
        "companions": 1.5,      # Existing tests are the reference
        "routing": 1.0,
    },
    "review": {
        "primary": 1.0,
        "abstractions": 1.0,
        "network_edges": 1.2,
        "companions": 0.8,
        "routing": 1.0,
    },
    None: {                     # Default balanced allocation
        "primary": 1.0,
        "abstractions": 1.0,
        "network_edges": 1.0,
        "companions": 1.0,
        "routing": 1.0,
    },
}


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
            from ..engine.assertions import ContextExhaustionError
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


def _bm25_task_path_score(
    task_words: set,
    all_path_word_sets: dict,
    target_path: str,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    """BM25 score for task words against a file's path components.

    Uses IDF to upweight rare path terms ("ast") and downweight common ones
    ("test", "utils"). Binary TF since each word appears at most once per path.
    """
    import math

    target_words = all_path_word_sets.get(target_path, set())
    if not target_words:
        return 0.0

    N = len(all_path_word_sets)
    if N == 0:
        return 0.0

    # Average document length (in words)
    avgdl = sum(len(ws) for ws in all_path_word_sets.values()) / N
    dl = len(target_words)

    score = 0.0
    for term in task_words:
        if term not in target_words:
            continue

        # Document frequency: how many files contain this term
        df = sum(1 for ws in all_path_word_sets.values() if term in ws)

        # IDF: rare terms score higher
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

        # TF is binary (0 or 1); BM25 TF normalization
        tf = 1.0
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))

        score += idf * tf_norm

    return score


def _rank_files(
    files: List[str],
    task: Optional[str] = None,
    utility_scores: Optional[dict] = None,
    file_scores: Optional[dict] = None,
    co_change_index: Optional[dict] = None,
    network_edges: Optional[dict] = None,
    reverse_network_edges: Optional[dict] = None,
) -> List[tuple]:
    """Rank files by relevance, layering multiple signals.

    Signals (in priority order):
    1. Scope match score — files from higher-scoring scopes rank higher
    2. Co-change affinity — files that co-change with other candidates get boosted
    2b. Network companion — cross-language contract partners get boosted
    3. Task-path overlap — task description words matching path components
    4. Historical utility — files agents actually modify rank higher
    5. Static heuristics — test/fixture penalty, file size bonus/penalty
    """
    import os
    from ..engine.utility import effective_score as _effective_score

    task_words = set()
    if task:
        task_words = {w.lower() for w in task.split() if len(w) > 2}

    file_set = set(files)

    # Pre-compute path word sets for BM25
    all_path_word_sets: dict = {}
    for path in files:
        rel_parts = path.lower().split(os.sep)
        words = set()
        for part in rel_parts:
            words.update(
                w for w in part.replace("_", " ").replace("-", " ").replace(".", " ").split()
                if len(w) > 2
            )
        all_path_word_sets[path] = words

    scored = []
    for path in files:
        score = 1.0
        basename = os.path.basename(path).lower()
        rel_parts = path.lower().split(os.sep)

        # Static heuristics
        if any(p in ("tests", "test", "fixtures", "migrations", "__pycache__") for p in rel_parts):
            score *= 0.5

        if basename.endswith((".generated.py", ".generated.ts", ".lock", ".min.js")):
            score *= 0.3

        # Signal 1: Scope match score — files from better-matching scopes rank higher
        if file_scores and path in file_scores:
            scope_score = file_scores[path]
            score *= 1.0 + scope_score  # e.g., 0.35 match → 1.35x boost

        # Signal 2: Co-change affinity — boost files that co-change with other candidates
        if co_change_index:
            partners = co_change_index.get(path, {})
            affinity = sum(
                conf for partner, conf in partners.items()
                if partner in file_set and partner != path
            )
            if affinity > 0:
                score *= 1.0 + min(affinity, 1.0)  # cap at 2x boost

        # Signal 2b: Network companion — cross-language contract partners
        if network_edges or reverse_network_edges:
            has_companion = False
            if network_edges:
                for companion in network_edges.get(path, {}):
                    if companion in file_set:
                        has_companion = True
                        break
            if not has_companion and reverse_network_edges:
                for provider in reverse_network_edges.get(path, []):
                    if provider in file_set:
                        has_companion = True
                        break
            if has_companion:
                score *= 1.5

        # Signal 3: BM25 task-path matching (IDF-weighted, penalizes common terms)
        if task_words and all_path_word_sets:
            bm25 = _bm25_task_path_score(
                task_words, all_path_word_sets, path,
            )
            if bm25 > 0:
                score *= 1.0 + min(bm25, 3.0)  # cap at 4x boost

        # Signal 5: File size heuristics
        tokens = estimate_file_tokens(path)
        if tokens > 0:
            if tokens < 200:
                score *= 1.2
            elif tokens > 2000:
                score *= 0.8

        # Signal 4: Historical utility
        utility = utility_scores.get(path) if utility_scores else None
        score = _effective_score(score, utility, is_explicit_include=True)

        scored.append((path, score, tokens))

    # Signal 6: Test companion — if a source file scores high, boost its test file
    # Build source→score lookup (non-test files only)
    source_scores = {
        path: score for path, score, _ in scored
        if not any(p in ("tests", "test") for p in path.lower().split(os.sep))
    }
    final = []
    for path, score, tokens in scored:
        rel_parts_check = path.lower().split(os.sep)
        if any(p in ("tests", "test") for p in rel_parts_check):
            basename_test = os.path.basename(path).lower()
            # test_cli.py → cli.py; strip leading test_ or trailing _test
            source_name = basename_test
            if source_name.startswith("test_"):
                source_name = source_name[5:]  # strip test_
            elif source_name.endswith("_test.py"):
                source_name = source_name[:-8] + ".py"
            # Search pool for matching source file
            best_source_score = 0.0
            for src_path, src_score in source_scores.items():
                if os.path.basename(src_path).lower() == source_name:
                    best_source_score = max(best_source_score, src_score)
            if best_source_score > 0:
                score *= 1.0 + (best_source_score * 0.5)  # companion lift
        final.append((path, score, tokens))

    final.sort(key=lambda x: (-x[1], x[2]))
    return [(path, score) for path, score, _ in final]


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
