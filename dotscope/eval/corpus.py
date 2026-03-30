"""Eval corpus: generate and manage task sets from git history.

Builds a corpus of historical commits suitable for replay evaluation.
Each task records the commit hash, expected modified files, constraints
that should fire, and test files involved.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from ..models.eval import EvalCorpus, EvalTask

# Commit size filter: skip trivial (1 file) and massive (>20 files) commits
MIN_FILES_PER_COMMIT = 2
MAX_FILES_PER_COMMIT = 20

# Test file patterns
_TEST_PATTERNS = [
    re.compile(r"tests?/"),
    re.compile(r"_test\.\w+$"),
    re.compile(r"test_\w+\.\w+$"),
    re.compile(r"\.test\.\w+$"),
    re.compile(r"\.spec\.\w+$"),
]


def generate_corpus(
    repo_root: str,
    max_commits: int = 200,
    min_files: int = MIN_FILES_PER_COMMIT,
    max_files: int = MAX_FILES_PER_COMMIT,
    run_checks: bool = False,
) -> EvalCorpus:
    """Generate an eval corpus from recent git history.

    Args:
        repo_root: Repository root path.
        max_commits: Maximum commits to scan.
        min_files: Minimum modified files per commit to include.
        max_files: Maximum modified files per commit to include.
        run_checks: If True, run check_diff post-hoc to populate expected_constraints.
    """
    raw_commits = _get_commits_with_messages(repo_root, max_commits)
    tasks: List[EvalTask] = []

    for commit_hash, message, files in raw_commits:
        if len(files) < min_files or len(files) > max_files:
            continue

        test_files = [f for f in files if _is_test_file(f)]
        non_test_files = [f for f in files if not _is_test_file(f)]

        if not non_test_files:
            continue

        expected_constraints: List[str] = []
        if run_checks:
            expected_constraints = _get_post_hoc_constraints(repo_root, commit_hash)

        task_desc = _synthesize_task(message, non_test_files)

        tasks.append(EvalTask(
            commit_hash=commit_hash,
            task_description=task_desc,
            expected_files=files,
            expected_constraints=expected_constraints,
            expected_tests=test_files,
        ))

    return EvalCorpus(
        tasks=tasks,
        repo_root=repo_root,
    )


def save_corpus(corpus: EvalCorpus, repo_root: str) -> str:
    """Save corpus to .dotscope/eval/corpus.json. Returns the file path."""
    eval_dir = Path(repo_root) / ".dotscope" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "repo_root": corpus.repo_root,
        "baseline_candidate": corpus.baseline_candidate,
        "min_tasks": corpus.min_tasks,
        "tasks": [
            {
                "commit_hash": t.commit_hash,
                "task_description": t.task_description,
                "expected_files": t.expected_files,
                "expected_constraints": t.expected_constraints,
                "expected_tests": t.expected_tests,
                "baseline_tokens": t.baseline_tokens,
            }
            for t in corpus.tasks
        ],
    }

    path = eval_dir / "corpus.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(path)


def load_corpus(repo_root: str) -> Optional[EvalCorpus]:
    """Load corpus from .dotscope/eval/corpus.json."""
    path = Path(repo_root) / ".dotscope" / "eval" / "corpus.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None

    tasks = [
        EvalTask(**t)
        for t in data.get("tasks", [])
    ]

    return EvalCorpus(
        tasks=tasks,
        repo_root=data.get("repo_root", repo_root),
        baseline_candidate=data.get("baseline_candidate", ""),
        min_tasks=data.get("min_tasks", 30),
    )


def corpus_id(corpus: EvalCorpus) -> str:
    """Deterministic hash of a corpus for comparison tracking."""
    hashes = sorted(t.commit_hash for t in corpus.tasks)
    return hashlib.sha256("|".join(hashes).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _get_commits_with_messages(
    root: str, n: int,
) -> List[tuple]:
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


def _is_test_file(path: str) -> bool:
    return any(p.search(path) for p in _TEST_PATTERNS)


def _synthesize_task(commit_message: str, files: List[str]) -> str:
    """Turn a commit message into a plausible task description."""
    msg = commit_message.strip()
    if not msg:
        dirs = sorted(set(os.path.dirname(f) for f in files if "/" in f))
        if dirs:
            return f"Make changes in {', '.join(dirs[:3])}"
        return "Make changes to the codebase"
    return msg


def _get_post_hoc_constraints(repo_root: str, commit_hash: str) -> List[str]:
    """Run check_diff on a commit's diff to get expected constraints."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}^", commit_hash],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    try:
        from ..passes.sentinel.checker import check_diff
        report = check_diff(result.stdout, repo_root)
        return [
            r.acknowledge_id
            for r in report.results
            if r.acknowledge_id
        ]
    except Exception:
        return []
