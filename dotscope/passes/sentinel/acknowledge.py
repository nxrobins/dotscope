"""Acknowledgment recording and confidence decay."""

import json
import os
import time
from typing import Dict, List, Optional

# Defaults (overridable via .dotscope/config.yaml)
DECAY_RATE = 0.1
DECAY_THRESHOLD = 3
DECAY_WINDOW_DAYS = 30
MIN_CONFIDENCE = 0.3


def record_acknowledgment(
    repo_root: str,
    ack_id: str,
    reason: str,
    session_id: Optional[str] = None,
) -> dict:
    """Record an acknowledgment in .dotscope/acknowledgments.jsonl."""
    dot_dir = os.path.join(repo_root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)

    entry = {
        "id": ack_id,
        "reason": reason,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id or "",
    }

    path = os.path.join(dot_dir, "acknowledgments.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def load_acknowledgments(repo_root: str) -> List[dict]:
    """Load all acknowledgments."""
    path = os.path.join(repo_root, ".dotscope", "acknowledgments.jsonl")
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def is_acknowledged(repo_root: str, ack_id: str) -> bool:
    """Check if a hold has been acknowledged.

    Returns True if previously acknowledged AND confidence has not
    decayed below the HOLD threshold (0.5). Constraints acknowledged
    3+ times within 30 days lose confidence — below 0.5 they become
    NOTEs instead of HOLDs, so this returns False (not "acknowledged"
    as a HOLD pass-through).
    """
    acks = load_acknowledgments(repo_root)
    if not any(a["id"] == ack_id for a in acks):
        return False

    # Apply decay: if confidence drops below 0.5, the constraint
    # should remain active (as a NOTE), not be silently passed
    confidence = compute_decayed_confidence(1.0, ack_id, acks)
    return confidence >= 0.5


def compute_decayed_confidence(
    base_confidence: float,
    ack_id: str,
    acknowledgments: List[dict],
) -> float:
    """Apply confidence decay based on repeated acknowledgments.

    After DECAY_THRESHOLD acknowledgments within DECAY_WINDOW_DAYS,
    each additional acknowledgment drops confidence by DECAY_RATE.
    Never drops below MIN_CONFIDENCE.
    """
    now = time.time()
    window_seconds = DECAY_WINDOW_DAYS * 86400

    recent = [
        a for a in acknowledgments
        if a.get("id") == ack_id and _parse_timestamp(a.get("timestamp", "")) > now - window_seconds
    ]

    count = len(recent)
    if count <= DECAY_THRESHOLD:
        return base_confidence

    excess = count - DECAY_THRESHOLD
    decayed = base_confidence - (excess * DECAY_RATE)
    return max(decayed, MIN_CONFIDENCE)


def _parse_timestamp(ts: str) -> float:
    """Parse ISO timestamp to epoch seconds."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0
