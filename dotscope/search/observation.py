"""Retrieval usage observation: log searches, correlate with commits, learn.

Closes the feedback loop: which search results were useful (modified in
subsequent commits) and which were noise (returned but never touched).
Usage scores feed back into the reranker as multiplicative adjustments.
"""

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class RetrievalObservation:
    """A single search-then-commit observation."""
    session_id: str
    query: str
    timestamp: str
    returned_files: List[str]
    returned_scores: Dict[str, float]
    committed_files: List[str] = field(default_factory=list)


@dataclass
class FileRetrievalStats:
    """Accumulated retrieval usage statistics per file."""
    file_path: str
    times_returned: int = 0
    times_hit: int = 0        # Returned and subsequently modified
    times_ignored: int = 0    # Returned but not modified
    times_missed: int = 0     # Modified but not returned in preceding search
    usage_score: float = 0.0  # hit_rate - ignore_rate, bounded [-1, 1]


# Per-process session ID fallback
_PROCESS_SESSION_ID = str(uuid.uuid4())[:8]

# Minimum observations before usage score is applied
MIN_OBSERVATIONS = 3


def get_session_id() -> str:
    """Get the current session ID (per-process fallback)."""
    return _PROCESS_SESSION_ID


def log_retrieval(
    root: str,
    session_id: str,
    query: str,
    returned_files: List[str],
    returned_scores: Dict[str, float],
) -> None:
    """Append a retrieval event to the log."""
    cache_dir = Path(root) / ".dotscope" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    log_path = cache_dir / "retrieval_log.jsonl"

    entry = {
        "session_id": session_id,
        "query": query,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "returned": returned_files,
        "scores": returned_scores,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_commit(
    root: str,
    session_id: str,
    commit_hash: str,
    modified_files: List[str],
) -> None:
    """Append a commit event to the log."""
    cache_dir = Path(root) / ".dotscope" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    log_path = cache_dir / "commit_log.jsonl"

    entry = {
        "session_id": session_id,
        "commit": commit_hash,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modified": modified_files,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def correlate_retrieval_with_commits(
    root: str,
    window_minutes: int = 30,
) -> List[RetrievalObservation]:
    """Match each retrieval event with the next commit within the time window.

    Correlation is scoped by session_id. A retrieval from Agent A is only
    matched with commits from Agent A.
    """
    cache_dir = Path(root) / ".dotscope" / "cache"
    retrieval_log = cache_dir / "retrieval_log.jsonl"
    commit_log = cache_dir / "commit_log.jsonl"

    if not retrieval_log.exists() or not commit_log.exists():
        return []

    retrievals = _load_jsonl(retrieval_log)
    commits = _load_jsonl(commit_log)

    # Group by session_id
    ret_by_session: Dict[str, list] = {}
    for r in retrievals:
        sid = r.get("session_id", "")
        ret_by_session.setdefault(sid, []).append(r)

    com_by_session: Dict[str, list] = {}
    for c in commits:
        sid = c.get("session_id", "")
        com_by_session.setdefault(sid, []).append(c)

    observations = []
    window_seconds = window_minutes * 60

    for sid, rets in ret_by_session.items():
        session_commits = com_by_session.get(sid, [])
        if not session_commits:
            continue

        for ret in rets:
            ret_time = _parse_ts(ret.get("ts", ""))
            if not ret_time:
                continue

            # Find next commit within window
            best_commit = None
            best_delta = window_seconds + 1
            for com in session_commits:
                com_time = _parse_ts(com.get("ts", ""))
                if not com_time:
                    continue
                delta = com_time - ret_time
                if 0 <= delta < window_seconds and delta < best_delta:
                    best_commit = com
                    best_delta = delta

            if best_commit:
                observations.append(RetrievalObservation(
                    session_id=sid,
                    query=ret.get("query", ""),
                    timestamp=ret.get("ts", ""),
                    returned_files=ret.get("returned", []),
                    returned_scores=ret.get("scores", {}),
                    committed_files=best_commit.get("modified", []),
                ))

    return observations


def compute_file_stats(
    observations: List[RetrievalObservation],
) -> Dict[str, FileRetrievalStats]:
    """Aggregate per-file retrieval statistics.

    usage_score = (hit_rate - ignore_rate), bounded [-1, 1].
    Files with fewer than MIN_OBSERVATIONS get usage_score = 0.0.
    """
    stats: Dict[str, FileRetrievalStats] = {}

    for obs in observations:
        returned_set = set(obs.returned_files)
        committed_set = set(obs.committed_files)

        hits = returned_set & committed_set
        ignored = returned_set - committed_set
        missed = committed_set - returned_set

        for f in returned_set | committed_set:
            if f not in stats:
                stats[f] = FileRetrievalStats(file_path=f)

        for f in returned_set:
            stats[f].times_returned += 1
        for f in hits:
            stats[f].times_hit += 1
        for f in ignored:
            stats[f].times_ignored += 1
        for f in missed:
            stats[f].times_missed += 1

    # Compute usage scores
    for s in stats.values():
        if s.times_returned >= MIN_OBSERVATIONS:
            hit_rate = s.times_hit / s.times_returned
            ignore_rate = s.times_ignored / s.times_returned
            s.usage_score = max(-1.0, min(1.0, hit_rate - ignore_rate))
        else:
            s.usage_score = 0.0

    return stats


def save_file_stats(root: str, stats: Dict[str, FileRetrievalStats]) -> None:
    """Persist file retrieval stats to cache."""
    cache_dir = Path(root) / ".dotscope" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "retrieval_stats.json"
    data = {k: asdict(v) for k, v in stats.items()}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_file_stats(root: str) -> Dict[str, FileRetrievalStats]:
    """Load file retrieval stats from cache."""
    path = Path(root) / ".dotscope" / "cache" / "retrieval_stats.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: FileRetrievalStats(**v) for k, v in data.items()}
    except Exception:
        return {}


def prune_old_logs(root: str, max_age_days: int = 90) -> int:
    """Remove log entries older than max_age_days. Returns count removed."""
    import datetime
    cutoff = time.time() - (max_age_days * 86400)
    removed = 0

    for log_name in ("retrieval_log.jsonl", "commit_log.jsonl"):
        log_path = Path(root) / ".dotscope" / "cache" / log_name
        if not log_path.exists():
            continue
        entries = _load_jsonl(log_path)
        kept = []
        for entry in entries:
            ts = _parse_ts(entry.get("ts", ""))
            if ts and ts >= cutoff:
                kept.append(entry)
            else:
                removed += 1
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in kept:
                f.write(json.dumps(entry) + "\n")

    return removed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list:
    """Load a JSONL file."""
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        pass
    return entries


def _parse_ts(ts: str) -> Optional[float]:
    """Parse ISO timestamp to epoch seconds."""
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None
