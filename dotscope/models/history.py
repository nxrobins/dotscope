"""History data models: the empirical ledger from git mining."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class FileChange:
    """A file changed in a commit, with line counts."""
    path: str
    insertions: int = 0
    deletions: int = 0

    @property
    def magnitude(self) -> int:
        return self.insertions + self.deletions


@dataclass
class CommitInfo:
    """A single git commit."""
    hash: str
    timestamp: str
    message: str
    files: List[str] = field(default_factory=list)
    changes: List[FileChange] = field(default_factory=list)

    @property
    def total_lines(self) -> int:
        return sum(c.magnitude for c in self.changes)


@dataclass
class FileHistory:
    """History stats for a single file."""
    path: str
    commit_count: int = 0
    total_lines_changed: int = 0
    last_modified: str = ""
    stability: str = ""  # "stable", "volatile", "tweaked"


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
    recent_summaries: Dict[str, List[str]] = field(default_factory=dict)  # module -> commit messages
    module_churn: Dict[str, int] = field(default_factory=dict)  # module -> total changes
