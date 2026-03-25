"""Session tracking and observation: the feedback loop.

Sessions record what dotscope predicted an agent would need.
Observations record what actually happened (post-commit).
Together they close the loop between prediction and reality.

All data is append-only. Derived views (utility scores, lessons)
are computed from these logs and can be rebuilt.
"""

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional

from .models import ObservationLog, SessionLog


class SessionManager:
    """Manages the .dotscope/ state directory and the session lifecycle."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.dot_dir = self.root / ".dotscope"
        self.sessions_dir = self.dot_dir / "sessions"
        self.obs_dir = self.dot_dir / "observations"

    def ensure_initialized(self):
        """Create .dotscope/ with schema version and .gitignore."""
        for d in [self.sessions_dir, self.obs_dir]:
            d.mkdir(parents=True, exist_ok=True)

        version_file = self.dot_dir / "schema_version"
        if not version_file.exists():
            version_file.write_text("1", encoding="utf-8")

        gitignore = self.dot_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")

    def create_session(
        self,
        scope_expr: str,
        task: Optional[str],
        files: List[str],
        context: str,
    ) -> str:
        """Record a scope resolution event (the prediction). Returns session ID."""
        self.ensure_initialized()

        session_id = uuid.uuid4().hex[:8]
        session = SessionLog(
            session_id=session_id,
            timestamp=time.time(),
            scope_expr=scope_expr,
            task=task,
            predicted_files=files,
            context_hash=hashlib.sha256(context.encode()).hexdigest()[:16],
        )

        path = self.sessions_dir / f"{session_id}.json"
        path.write_text(json.dumps({
            "session_id": session.session_id,
            "timestamp": session.timestamp,
            "scope_expr": session.scope_expr,
            "task": session.task,
            "predicted_files": session.predicted_files,
            "context_hash": session.context_hash,
        }, indent=2), encoding="utf-8")

        return session_id

    def record_observation(self, commit_hash: str) -> Optional[ObservationLog]:
        """Match a commit to a session and log what actually happened."""
        self.ensure_initialized()

        modified_files = self._get_commit_files(commit_hash)
        if not modified_files:
            return None

        session = self._find_relevant_session(modified_files)
        if not session:
            return None

        predicted_set = set(session.predicted_files)
        actual_set = set(modified_files)

        intersection = predicted_set & actual_set
        predicted_not_touched = sorted(predicted_set - actual_set)
        touched_not_predicted = sorted(actual_set - predicted_set)

        recall = len(intersection) / len(actual_set) if actual_set else 1.0
        precision = len(intersection) / len(predicted_set) if predicted_set else 1.0

        obs = ObservationLog(
            commit_hash=commit_hash,
            session_id=session.session_id,
            actual_files_modified=modified_files,
            predicted_not_touched=predicted_not_touched,
            touched_not_predicted=touched_not_predicted,
            recall=round(recall, 3),
            precision=round(precision, 3),
            timestamp=time.time(),
        )

        path = self.obs_dir / f"{commit_hash[:8]}.json"
        path.write_text(json.dumps({
            "commit_hash": obs.commit_hash,
            "session_id": obs.session_id,
            "actual_files_modified": obs.actual_files_modified,
            "predicted_not_touched": obs.predicted_not_touched,
            "touched_not_predicted": obs.touched_not_predicted,
            "recall": obs.recall,
            "precision": obs.precision,
            "timestamp": obs.timestamp,
        }, indent=2), encoding="utf-8")

        return obs

    def get_sessions(self, limit: int = 50) -> List[SessionLog]:
        """Load recent sessions, newest first."""
        sessions = []
        for p in sorted(self.sessions_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            if len(sessions) >= limit:
                break
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                sessions.append(SessionLog(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return sessions

    def get_observations(self, limit: int = 50) -> List[ObservationLog]:
        """Load recent observations, newest first."""
        observations = []
        for p in sorted(self.obs_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            if len(observations) >= limit:
                break
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                observations.append(ObservationLog(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return observations

    def _get_commit_files(self, commit_hash: str) -> List[str]:
        """Extract modified files from a commit."""
        try:
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
                cwd=str(self.root),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]

    def _find_relevant_session(self, modified_files: List[str]) -> Optional[SessionLog]:
        """Match a commit to the best-fit session via Jaccard overlap.

        Only considers sessions from the last 4 hours.
        Requires minimum 10% Jaccard score to avoid spurious matches.
        """
        modified_set = set(modified_files)
        best_session = None
        best_score = 0.0
        cutoff = time.time() - (4 * 3600)

        for p in sorted(self.sessions_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            if os.path.getmtime(p) < cutoff:
                break
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                session = SessionLog(**data)
            except (json.JSONDecodeError, TypeError):
                continue

            predicted_set = set(session.predicted_files)
            intersection = modified_set & predicted_set
            union = modified_set | predicted_set
            jaccard = len(intersection) / len(union) if union else 0.0

            if jaccard > best_score:
                best_score = jaccard
                best_session = session

        if best_score < 0.1:
            return None
        return best_session
