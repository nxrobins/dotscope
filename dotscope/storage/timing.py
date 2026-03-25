"""Lightweight timing instrumentation for core operations."""

import json
import os
import time
from dataclasses import dataclass
from typing import List


@dataclass
class TimingEntry:
    operation: str  # "resolve", "check", "ingest"
    duration_ms: float
    timestamp: str


def record_timing(repo_root: str, operation: str, duration_ms: float) -> None:
    """Append a timing entry to .dotscope/timings.jsonl."""
    dot_dir = os.path.join(repo_root, ".dotscope")
    if not os.path.isdir(dot_dir):
        return  # No .dotscope dir — skip silently

    path = os.path.join(dot_dir, "timings.jsonl")
    entry = {
        "operation": operation,
        "duration_ms": round(duration_ms, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def load_timings(repo_root: str) -> List[TimingEntry]:
    """Load all timing entries."""
    path = os.path.join(repo_root, ".dotscope", "timings.jsonl")
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                    entries.append(TimingEntry(
                        operation=d["operation"],
                        duration_ms=d["duration_ms"],
                        timestamp=d.get("timestamp", ""),
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue
    return entries


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def percentile(values: List[float], p: int) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]
