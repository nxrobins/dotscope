"""Recency and stability re-ranking.

Applies multiplicative adjustments to search scores based on code
liveness from FileHistory.
"""

from typing import Dict, List, Optional

from .models import SearchResult


def apply_recency_rerank(
    results: List[SearchResult],
    file_histories: Dict[str, dict],
) -> List[SearchResult]:
    """Re-rank search results by code liveness.

    Signals (multiplicative on rrf_score):
      - stability == "stable" AND last_modified > 6 months ago: x 0.75
      - stability == "volatile" AND last_modified < 7 days: x 1.20
      - stability == "volatile" AND last_modified < 30 days: x 1.10
      - No history data: x 1.0 (neutral)

    Args:
        results: Search results from Stage 1.
        file_histories: {file_path: {"stability": str, "last_modified": float}}
    """
    import time
    now = time.time()
    seven_days = 7 * 86400
    thirty_days = 30 * 86400
    six_months = 180 * 86400

    for result in results:
        history = file_histories.get(result.file_path)
        if not history:
            result.recency_adjusted = result.rrf_score
            continue

        stability = history.get("stability", "")
        last_mod = history.get("last_modified", 0)
        age = now - last_mod if last_mod > 0 else six_months + 1

        multiplier = 1.0
        if stability == "stable" and age > six_months:
            multiplier = 0.75
        elif stability == "volatile":
            if age < seven_days:
                multiplier = 1.20
            elif age < thirty_days:
                multiplier = 1.10

        result.recency_adjusted = result.rrf_score * multiplier

    results.sort(key=lambda r: -r.recency_adjusted)
    return results


def apply_usage_rerank(
    results: List[SearchResult],
    file_stats: Dict[str, dict],
) -> List[SearchResult]:
    """Layer retrieval usage signal onto re-ranking.

    Applied AFTER recency re-ranking, as a second multiplicative pass.

    Signals:
      - usage_score > 0.3 (consistently useful): x 1.15
      - usage_score < -0.3 (consistently ignored): x 0.85
      - insufficient data or neutral: x 1.0
    """
    for result in results:
        stats = file_stats.get(result.file_path)
        if not stats:
            continue

        score = stats.get("usage_score", 0.0) if isinstance(stats, dict) else getattr(stats, "usage_score", 0.0)

        if score > 0.3:
            result.recency_adjusted *= 1.15
        elif score < -0.3:
            result.recency_adjusted *= 0.85

    results.sort(key=lambda r: -r.recency_adjusted)
    return results
