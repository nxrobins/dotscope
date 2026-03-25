"""Git history mining: change coupling, hotspots, implicit contracts.

Reads git log to extract:
- Change coupling: files that always change together → same scope
- Hotspots: files with high churn → need richest context
- Implicit contracts: co-change patterns that reveal hidden dependencies
- Recent session summaries: what happened in the last N commits per module
"""


import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple


@dataclass
class CommitInfo:
    """A single git commit."""
    hash: str
    timestamp: str
    message: str
    files: List[str]


@dataclass
class FileHistory:
    """History stats for a single file."""
    path: str
    commit_count: int = 0
    last_modified: str = ""
    authors: List[str] = field(default_factory=list)


@dataclass
class ChangeCoupling:
    """Two files that frequently change together."""
    file_a: str
    file_b: str
    co_changes: int  # How many commits touch both
    total_a: int  # Total commits touching A
    total_b: int  # Total commits touching B
    coupling_strength: float = 0.0  # co_changes / min(total_a, total_b)


@dataclass
class ImplicitContract:
    """An observed pattern: when X changes, Y always changes too."""
    trigger_file: str
    coupled_file: str
    confidence: float  # How often Y changes when X changes
    occurrences: int
    description: str = ""


@dataclass
class HistoryAnalysis:
    """Full git history analysis results."""
    commits_analyzed: int = 0
    file_histories: Dict[str, FileHistory] = field(default_factory=dict)
    hotspots: List[Tuple[str, int]] = field(default_factory=list)  # (file, churn)
    change_couplings: List[ChangeCoupling] = field(default_factory=list)
    implicit_contracts: List[ImplicitContract] = field(default_factory=list)
    recent_summaries: Dict[str, List[str]] = field(default_factory=dict)  # module → commit messages
    module_churn: Dict[str, int] = field(default_factory=dict)  # module → total changes


def analyze_history(
    root: str,
    max_commits: int = 500,
    coupling_threshold: float = 0.5,
) -> HistoryAnalysis:
    """Mine git history for architectural signals.

    Args:
        root: Repository root
        max_commits: Maximum commits to analyze (most recent)
        coupling_threshold: Minimum coupling strength to report
    """
    if not os.path.isdir(os.path.join(root, ".git")):
        return HistoryAnalysis()

    commits = _parse_git_log(root, max_commits)
    if not commits:
        return HistoryAnalysis()

    analysis = HistoryAnalysis(commits_analyzed=len(commits))

    # Build per-file stats
    file_commits: Dict[str, List[str]] = defaultdict(list)  # file → [commit hashes]
    for commit in commits:
        for f in commit.files:
            file_commits[f].append(commit.hash)

    for path, commit_hashes in file_commits.items():
        analysis.file_histories[path] = FileHistory(
            path=path,
            commit_count=len(commit_hashes),
        )

    # Hotspots: files with highest churn
    churn = [(path, len(hashes)) for path, hashes in file_commits.items()]
    churn.sort(key=lambda x: -x[1])
    analysis.hotspots = churn[:30]

    # Module-level churn
    for path, count in churn:
        parts = path.split("/")
        if len(parts) > 1:
            module = parts[0]
            analysis.module_churn[module] = analysis.module_churn.get(module, 0) + count

    # Change coupling: files that co-occur in commits
    analysis.change_couplings = _compute_change_coupling(
        commits, file_commits, coupling_threshold
    )

    # Implicit contracts: when A changes, B almost always changes too
    analysis.implicit_contracts = _detect_implicit_contracts(
        commits, file_commits, threshold=0.7
    )

    # Recent summaries per module
    analysis.recent_summaries = _extract_recent_summaries(commits, limit_per_module=5)

    return analysis


def _parse_git_log(root: str, max_commits: int) -> List[CommitInfo]:
    """Parse git log into structured commits."""
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--max-count={max_commits}",
                "--pretty=format:%H|%aI|%s",
                "--name-only",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    commits = []
    current_commit = None
    current_files = []

    for line in result.stdout.splitlines():
        if "|" in line and len(line.split("|")) >= 3:
            # Save previous commit
            if current_commit:
                current_commit.files = current_files
                commits.append(current_commit)
                current_files = []

            parts = line.split("|", 2)
            current_commit = CommitInfo(
                hash=parts[0],
                timestamp=parts[1],
                message=parts[2],
                files=[],
            )
        elif line.strip() and current_commit:
            current_files.append(line.strip())

    # Don't forget last commit
    if current_commit:
        current_commit.files = current_files
        commits.append(current_commit)

    return commits


def _compute_change_coupling(
    commits: List[CommitInfo],
    file_commits: Dict[str, List[str]],
    threshold: float,
) -> List[ChangeCoupling]:
    """Find files that frequently change together."""
    # Build co-occurrence matrix (only for files with enough commits)
    active_files = {f for f, hashes in file_commits.items() if len(hashes) >= 3}
    co_change: Dict[Tuple[str, str], int] = Counter()

    for commit in commits:
        relevant = [f for f in commit.files if f in active_files]
        for i, a in enumerate(relevant):
            for b in relevant[i + 1:]:
                pair = tuple(sorted([a, b]))
                co_change[pair] += 1

    couplings = []
    for (a, b), count in co_change.items():
        total_a = len(file_commits[a])
        total_b = len(file_commits[b])
        strength = count / min(total_a, total_b) if min(total_a, total_b) > 0 else 0

        if strength >= threshold and count >= 3:
            couplings.append(ChangeCoupling(
                file_a=a, file_b=b,
                co_changes=count,
                total_a=total_a, total_b=total_b,
                coupling_strength=round(strength, 3),
            ))

    couplings.sort(key=lambda c: -c.coupling_strength)
    return couplings[:50]  # Top 50


def _detect_implicit_contracts(
    commits: List[CommitInfo],
    file_commits: Dict[str, List[str]],
    threshold: float,
) -> List[ImplicitContract]:
    """Detect patterns where changing file A almost always means changing file B.

    This reveals implicit contracts: "if you touch billing.py, you must update tests."
    """
    # For each file pair, compute P(B changes | A changes)
    contracts = []
    active_files = {f for f, h in file_commits.items() if len(h) >= 5}

    # Build commit sets for intersection
    file_commit_sets: Dict[str, Set[str]] = {
        f: set(file_commits[f]) for f in active_files
    }

    checked = set()
    for a in active_files:
        for b in active_files:
            if a == b:
                continue
            pair = (a, b)
            if pair in checked:
                continue
            checked.add(pair)

            intersection = file_commit_sets[a] & file_commit_sets[b]
            if not intersection:
                continue

            # P(B | A): when A changes, how often does B also change?
            confidence_a_to_b = len(intersection) / len(file_commit_sets[a])

            if confidence_a_to_b >= threshold and len(intersection) >= 3:
                # Determine if it's a test relationship
                desc = _describe_contract(a, b, confidence_a_to_b)
                contracts.append(ImplicitContract(
                    trigger_file=a,
                    coupled_file=b,
                    confidence=round(confidence_a_to_b, 3),
                    occurrences=len(intersection),
                    description=desc,
                ))

    contracts.sort(key=lambda c: -c.confidence)
    return contracts[:30]


def _describe_contract(trigger: str, coupled: str, confidence: float) -> str:
    """Generate a human-readable description of an implicit contract."""
    trigger_base = os.path.basename(trigger)
    coupled_base = os.path.basename(coupled)

    # Test file pattern
    if "test" in coupled.lower() and "test" not in trigger.lower():
        return f"When {trigger_base} changes, {coupled_base} is updated {confidence:.0%} of the time (test co-change)"

    # Same module, different files
    if os.path.dirname(trigger) == os.path.dirname(coupled):
        return f"{trigger_base} and {coupled_base} are tightly coupled within their module ({confidence:.0%} co-change)"

    # Cross-module
    return f"Changes to {trigger_base} require updates to {coupled_base} ({confidence:.0%} co-change)"


def _extract_recent_summaries(
    commits: List[CommitInfo], limit_per_module: int = 5
) -> Dict[str, List[str]]:
    """Extract recent commit messages grouped by module."""
    module_messages: Dict[str, List[str]] = defaultdict(list)

    for commit in commits:
        modules_touched = set()
        for f in commit.files:
            parts = f.split("/")
            if len(parts) > 1:
                modules_touched.add(parts[0])

        for module in modules_touched:
            if len(module_messages[module]) < limit_per_module:
                module_messages[module].append(commit.message)

    return dict(module_messages)


def format_history_summary(analysis: HistoryAnalysis) -> str:
    """Format a human-readable history analysis summary."""
    lines = [
        f"Git History: {analysis.commits_analyzed} commits analyzed",
        "",
    ]

    if analysis.hotspots:
        lines.append("Hotspots (highest churn):")
        for path, count in analysis.hotspots[:10]:
            bar = "█" * min(count, 30)
            lines.append(f"  {path}: {count} commits {bar}")
        lines.append("")

    if analysis.change_couplings:
        lines.append("Change Coupling (files that change together):")
        for cc in analysis.change_couplings[:10]:
            lines.append(
                f"  {cc.file_a} <-> {cc.file_b}: "
                f"{cc.coupling_strength:.0%} ({cc.co_changes} co-changes)"
            )
        lines.append("")

    if analysis.implicit_contracts:
        lines.append("Implicit Contracts:")
        for ic in analysis.implicit_contracts[:10]:
            lines.append(f"  {ic.description}")
        lines.append("")

    return "\n".join(lines)
