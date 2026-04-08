"""Task-to-scope matching via keyword overlap.

Given a natural language task description, find which scope(s) are most relevant.
Uses Jaccard similarity over keywords, with optional embedding fallback.
"""


import re
from typing import List, Tuple


# Common stop words to exclude from matching
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "about",
    "like", "through", "after", "before", "between", "under", "above",
    "it", "its", "this", "that", "these", "those", "i", "me", "my", "we",
    "our", "you", "your", "he", "she", "they", "them", "and", "but", "or",
    "not", "no", "if", "then", "so", "very", "just", "also", "only",
    "fix", "add", "update", "change", "make", "get", "set", "new",
}


def match_task(
    task: str,
    scopes: List[Tuple[str, List[str], str]],
    threshold: float = 0.05,
) -> List[Tuple[str, float]]:
    """Match a task description to the most relevant scope(s).

    Args:
        task: Natural language task description
        scopes: List of (scope_name, keywords, description) tuples
        threshold: Minimum score to include in results

    Returns:
        List of (scope_name, score) sorted by relevance descending
    """
    task_words = _tokenize(task)
    if not task_words:
        return []

    results = []
    for name, keywords, description in scopes:
        score = _score_scope(task_words, name, keywords, description)
        if score >= threshold:
            results.append((name, score))

    results.sort(key=lambda x: -x[1])
    return results


def _score_scope(
    task_words: set,
    scope_name: str,
    keywords: List[str],
    description: str,
) -> float:
    """Score how well a scope matches a task.

    Combines:
    1. Jaccard similarity between task words and scope keywords
    2. Substring match of scope name in task
    3. Word overlap with description
    """
    score = 0.0

    # Keyword match (Jaccard similarity)
    kw_words = set()
    for kw in keywords:
        kw_words.update(_tokenize(kw))

    if kw_words:
        intersection = task_words & kw_words
        union = task_words | kw_words
        if union:
            jaccard = len(intersection) / len(union)
            score += jaccard * 0.6  # 60% weight on keyword match

    # Scope name match
    name_words = _tokenize(scope_name)
    if name_words & task_words:
        score += 0.25  # 25% bonus for name match

    # Also check if scope name appears as substring in task
    if scope_name.lower() in " ".join(task_words):
        score += 0.1

    # Description word overlap
    desc_words = _tokenize(description)
    if desc_words:
        desc_overlap = task_words & desc_words
        if desc_overlap:
            score += (len(desc_overlap) / len(desc_words)) * 0.15  # 15% weight

    return min(score, 1.0)


def _tokenize(text: str) -> set:
    """Tokenize text into lowercase words, stripping stop words and punctuation."""
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if len(w) > 1 and w not in _STOP_WORDS}
