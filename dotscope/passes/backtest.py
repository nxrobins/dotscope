"""Scope backtesting: validate generated scopes against actual git history.

Replays recent commits and measures whether each scope's includes would have
covered the files that were actually changed. Self-corrects by suggesting
missing includes.
"""

import os
import subprocess
from collections import defaultdict
from typing import Dict, List, Set

from ..models import (
    BacktestReport,
    BacktestResult,
    MissingSuggestion,
    ScopeConfig,
)
from ..resolver import resolve


def backtest_scopes(
    root: str,
    scopes: List[ScopeConfig],
    n_commits: int = 50,
) -> BacktestReport:
    """Validate scopes against git history.

    For each recent commit, check whether the matched scope's resolved
    file list would have included all changed files.
    """
    commits = _get_recent_commits(root, n_commits)
    if not commits:
        return BacktestReport()

    # Resolve each scope to its file set, keyed by relative directory name
    scope_file_sets: Dict[str, Set[str]] = {}
    scope_dirs: Dict[str, ScopeConfig] = {}

    for scope in scopes:
        resolved = resolve(scope, follow_related=False, root=root)
        rel_dir = os.path.relpath(scope.directory, root)
        scope_file_sets[rel_dir] = set(resolved.files)
        scope_dirs[rel_dir] = scope

    # Track per-scope results
    scope_commits: Dict[str, int] = defaultdict(int)
    scope_covered: Dict[str, int] = defaultdict(int)
    scope_misses: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for commit_files in commits:
        # Match commit to scope(s) by directory prefix
        matched_scopes = _match_commit_to_scopes(commit_files, scope_dirs, root)

        for scope_dir in matched_scopes:
            scope_commits[scope_dir] += 1
            file_set = scope_file_sets.get(scope_dir, set())

            all_covered = True
            for changed_file in commit_files:
                abs_changed = os.path.join(root, changed_file)
                if abs_changed not in file_set:
                    all_covered = False
                    scope_misses[scope_dir][changed_file] += 1

            if all_covered:
                scope_covered[scope_dir] += 1

    # Build results
    results = []
    for scope in scopes:
        d = os.path.relpath(scope.directory, root)
        total = scope_commits.get(d, 0)
        covered = scope_covered.get(d, 0)
        recall = covered / total if total > 0 else 1.0

        misses = []
        for path, count in sorted(
            scope_misses.get(d, {}).items(), key=lambda x: -x[1]
        ):
            if count >= 2:  # Only suggest files that appear multiple times
                misses.append(MissingSuggestion(
                    path=path,
                    appearances=count,
                    would_improve_recall=True,
                ))

        results.append(BacktestResult(
            scope_path=scope.path,
            total_commits=total,
            fully_covered=covered,
            recall=round(recall, 3),
            missing_includes=misses[:10],
        ))

    total_commits = len(commits)
    total_covered = sum(r.fully_covered for r in results)
    total_matched = sum(r.total_commits for r in results)
    overall_recall = total_covered / total_matched if total_matched > 0 else 1.0

    return BacktestReport(
        results=results,
        total_commits=total_commits,
        overall_recall=round(overall_recall, 3),
    )


def auto_correct_scope(
    scope: ScopeConfig,
    result: BacktestResult,
    root: str,
    min_appearances: int = 3,
) -> tuple[ScopeConfig, bool]:
    """Auto-correct a scope's includes based on backtest results.

    Returns (updated_scope, changed) tuple.
    """
    changed = False
    for suggestion in result.missing_includes:
        if suggestion.appearances >= min_appearances and suggestion.would_improve_recall:
            if suggestion.path not in scope.includes:
                scope.includes.append(suggestion.path)
                changed = True
    return scope, changed


def format_backtest_report(report: BacktestReport) -> str:
    """Human-readable backtest report."""
    lines = [
        f"Backtest: {report.total_commits} commits analyzed",
        f"Overall recall: {report.overall_recall:.0%}",
        "",
    ]

    for result in report.results:
        scope_name = os.path.basename(os.path.dirname(result.scope_path))
        recall_bar = "█" * int(result.recall * 10) + "░" * (10 - int(result.recall * 10))
        lines.append(
            f"  {scope_name}/.scope — recall: {recall_bar} {result.recall:.0%} "
            f"({result.fully_covered}/{result.total_commits} commits)"
        )

        for miss in result.missing_includes[:5]:
            lines.append(f"    missing: {miss.path} (appeared in {miss.appearances} commits)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _get_recent_commits(root: str, n: int) -> List[List[str]]:
    """Get file lists from recent commits."""
    if not os.path.isdir(os.path.join(root, ".git")):
        return []

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n}", "--pretty=format:%H", "--name-only"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    commits = []
    current_files = []

    for line in result.stdout.splitlines():
        if len(line) == 40 and " " not in line:  # Commit hash
            if current_files:
                commits.append(current_files)
                current_files = []
        elif line.strip():
            current_files.append(line.strip())

    if current_files:
        commits.append(current_files)

    return commits


def _match_commit_to_scopes(
    commit_files: List[str],
    scope_dirs: Dict[str, ScopeConfig],
    root: str,
) -> Set[str]:
    """Match a commit's changed files to relevant scopes."""
    matched = set()
    for changed_file in commit_files:
        parts = changed_file.split("/")
        if len(parts) > 1:
            top_dir = parts[0]
            if top_dir in scope_dirs:
                matched.add(top_dir)
    return matched
