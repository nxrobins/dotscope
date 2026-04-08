"""Bootstrap observation data from git history.

Generates synthetic sessions and observations by replaying historical
commits through scope resolution. This builds the utility score base
that the ranker needs to make informed file selections.

Unlike the eval replay (which measures fitness), this writes real
.dotscope/ state that persists and improves future resolutions.
"""

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..models.state import ObservationLog, SessionLog


def bootstrap_observations(
    repo_root: str,
    max_commits: int = 200,
    min_files: int = 2,
    max_files: int = 30,
) -> Dict[str, int]:
    """Generate sessions + observations from git history.

    For each qualifying commit:
    1. Resolve scope(s) using the task description (commit message)
    2. Write a SessionLog (the prediction)
    3. Write an ObservationLog (the actual files changed)

    Returns summary stats.
    """
    from ..engine.composer import compose_for_task
    from ..engine.discovery import find_all_scopes
    from ..engine.parser import parse_scope_file
    from ..engine.resolver import resolve

    dot_dir = Path(repo_root) / ".dotscope"
    sessions_dir = dot_dir / "sessions"
    obs_dir = dot_dir / "observations"

    for d in [sessions_dir, obs_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Ensure .gitignore
    gitignore = dot_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")

    # Get commits with messages and file lists
    commits = _get_commits(repo_root, max_commits)

    # Build scope lookup for directory fallback
    scope_files = find_all_scopes(repo_root)
    scope_by_name = {}
    for sf in scope_files:
        try:
            config = parse_scope_file(sf)
            name = os.path.basename(os.path.dirname(config.path)) or "root"
            scope_by_name[name] = config
        except Exception:
            continue

    stats = {"commits_scanned": len(commits), "sessions_created": 0, "skipped": 0}

    for commit_hash, message, files in commits:
        if len(files) < min_files or len(files) > max_files:
            stats["skipped"] += 1
            continue

        # Try compose_for_task first
        resolved = compose_for_task(message, root=repo_root, max_scopes=2)

        # Fallback: directory matching
        if not resolved.files:
            resolved = _resolve_by_directory(files, scope_by_name, repo_root, resolve)

        if not resolved.files:
            stats["skipped"] += 1
            continue

        # Get predicted files as relative paths
        predicted = [
            os.path.relpath(f, repo_root) if os.path.isabs(f) else f
            for f in resolved.files
        ]

        # Write session
        session_id = uuid.uuid4().hex[:8]
        session = {
            "session_id": session_id,
            "timestamp": time.time(),
            "scope_expr": "bootstrap",
            "task": message,
            "predicted_files": predicted,
            "context_hash": hashlib.sha256(
                resolved.context.encode()
            ).hexdigest()[:16],
        }
        (sessions_dir / f"{session_id}.json").write_text(
            json.dumps(session, indent=2), encoding="utf-8",
        )

        # Write observation
        predicted_set = set(predicted)
        actual_set = set(files)
        intersection = predicted_set & actual_set
        predicted_not_touched = sorted(predicted_set - actual_set)
        touched_not_predicted = sorted(actual_set - predicted_set)

        recall = len(intersection) / len(actual_set) if actual_set else 1.0
        precision = len(intersection) / len(predicted_set) if predicted_set else 1.0

        obs = {
            "commit_hash": commit_hash,
            "session_id": session_id,
            "actual_files_modified": sorted(actual_set),
            "predicted_not_touched": predicted_not_touched,
            "touched_not_predicted": touched_not_predicted,
            "recall": round(recall, 3),
            "precision": round(precision, 3),
            "timestamp": time.time(),
        }
        (obs_dir / f"{commit_hash[:8]}.json").write_text(
            json.dumps(obs, indent=2), encoding="utf-8",
        )

        stats["sessions_created"] += 1

    # Rebuild utility scores from the new data
    _rebuild_utility(repo_root)

    return stats


def _get_commits(root: str, n: int) -> List[Tuple[str, str, List[str]]]:
    """Get (hash, message, [files]) for recent commits."""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n}", "--pretty=format:%H\t%s", "--name-only"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    commits = []
    current_hash = ""
    current_msg = ""
    current_files: List[str] = []

    for line in result.stdout.splitlines():
        if "\t" in line and len(line.split("\t")[0]) == 40:
            if current_hash and current_files:
                commits.append((current_hash, current_msg, current_files))
            parts = line.split("\t", 1)
            current_hash = parts[0]
            current_msg = parts[1] if len(parts) > 1 else ""
            current_files = []
        elif line.strip():
            current_files.append(line.strip())

    if current_hash and current_files:
        commits.append((current_hash, current_msg, current_files))

    return commits


def _resolve_by_directory(
    files: List[str],
    scope_by_name: dict,
    repo_root: str,
    resolve_fn,
) -> object:
    """Resolve scopes by matching file directory prefixes."""
    from collections import Counter
    from ..models import ResolvedScope

    dir_counts: Counter = Counter()
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            dir_counts[parts[0]] += 1

    matched = []
    for dirname, _count in dir_counts.most_common():
        if len(matched) >= 2:
            break
        for name, config in scope_by_name.items():
            scope_dir = os.path.basename(os.path.dirname(config.path))
            if (scope_dir == dirname or name == dirname) and name not in matched:
                matched.append(name)
                break

    if not matched:
        return ResolvedScope()

    result = None
    for i, name in enumerate(matched):
        config = scope_by_name.get(name)
        if not config:
            continue
        resolved = resolve_fn(config, follow_related=True, root=repo_root)
        weight = 1.0 / (1 + i)
        resolved.file_scores = {f: weight for f in resolved.files}
        if result is None:
            result = resolved
        else:
            result = result.merge(resolved)

    return result or ResolvedScope()


def _rebuild_utility(repo_root: str) -> None:
    """Rebuild utility scores from session + observation data."""
    from ..storage.session_manager import SessionManager
    from ..engine.utility import rebuild_utility

    dot_dir = Path(repo_root) / ".dotscope"
    mgr = SessionManager(repo_root)
    sessions = mgr.get_sessions(limit=500)
    observations = mgr.get_observations(limit=500)

    if sessions and observations:
        rebuild_utility(dot_dir, sessions, observations)
