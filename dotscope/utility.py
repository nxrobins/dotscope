"""Utility scoring: historical file relevance from observation data.

Computes per-file utility ratios from session + observation logs.
Files agents actually touch get higher scores. Budget allocation
uses these scores instead of static heuristics.

The utility floor prevents a death spiral: core abstractions that are
rarely edited but frequently read always retain a base weight.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from .models.state import FileUtilityScore, ObservationLog, SessionLog  # noqa: F401


BASE_UTILITY_WEIGHT = 0.5
MAX_UTILITY_BONUS = 1.0
MIN_SAMPLE_SIZE = 3


def compute_utility_scores(
    sessions: List[SessionLog],
    observations: List[ObservationLog],
) -> Dict[str, FileUtilityScore]:
    """Build utility scores from session + observation logs."""
    scores: Dict[str, FileUtilityScore] = {}

    # Count resolves per file
    for session in sessions:
        for f in session.predicted_files:
            if f not in scores:
                scores[f] = FileUtilityScore(path=f)
            scores[f].resolve_count += 1
            scores[f].last_resolved = max(scores[f].last_resolved, session.timestamp)

    # Count touches per file
    obs_by_session: Dict[str, ObservationLog] = {
        obs.session_id: obs for obs in observations
    }
    for session in sessions:
        obs = obs_by_session.get(session.session_id)
        if not obs:
            continue
        for f in obs.actual_files_modified:
            if f not in scores:
                scores[f] = FileUtilityScore(path=f)
            scores[f].touch_count += 1
            scores[f].last_touched = max(scores[f].last_touched, obs.timestamp)

    # Compute ratios
    for score in scores.values():
        if score.resolve_count > 0:
            score.utility_ratio = round(score.touch_count / score.resolve_count, 3)

    return scores


def effective_score(
    base_score: float,
    utility: Optional[FileUtilityScore],
    is_explicit_include: bool,
) -> float:
    """Compute effective score with utility floor protection.

    Explicit includes always get a base weight. Utility observations
    add on top, never subtract below the floor.
    """
    floor = BASE_UTILITY_WEIGHT if is_explicit_include else 0.0

    bonus = 0.0
    if utility and utility.resolve_count >= MIN_SAMPLE_SIZE:
        bonus = utility.utility_ratio * MAX_UTILITY_BONUS
        # Recency bonus: touched in last 30 days
        if utility.last_touched > time.time() - (30 * 86400):
            bonus *= 1.1

    return base_score * max(floor + bonus, floor) if floor else base_score * (1.0 + bonus)


def save_utility_scores(dot_dir: Path, scores: Dict[str, FileUtilityScore]) -> None:
    """Write utility scores to .dotscope/utility/file_scores.json."""
    utility_dir = dot_dir / "utility"
    utility_dir.mkdir(parents=True, exist_ok=True)

    data = {
        path: {
            "resolve_count": s.resolve_count,
            "touch_count": s.touch_count,
            "utility_ratio": s.utility_ratio,
            "last_touched": s.last_touched,
            "last_resolved": s.last_resolved,
        }
        for path, s in scores.items()
    }

    (utility_dir / "file_scores.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_utility_scores(dot_dir: Path) -> Dict[str, FileUtilityScore]:
    """Load utility scores from .dotscope/utility/file_scores.json."""
    path = dot_dir / "utility" / "file_scores.json"
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            k: FileUtilityScore(path=k, **v)
            for k, v in data.items()
        }
    except (json.JSONDecodeError, TypeError):
        return {}


def rebuild_utility(dot_dir: Path, sessions: List[SessionLog],
                    observations: List[ObservationLog]) -> Dict[str, FileUtilityScore]:
    """Rebuild and save utility scores from event logs."""
    scores = compute_utility_scores(sessions, observations)
    save_utility_scores(dot_dir, scores)
    return scores
