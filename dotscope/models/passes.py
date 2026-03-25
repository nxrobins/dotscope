"""Pass data models: ephemeral outputs from analysis passes."""

from dataclasses import dataclass, field
from typing import List, Optional

from .core import DependencyGraph, ScopeConfig, ScopesIndex, ScopeEntry
from .history import HistoryAnalysis
from .state import BacktestReport


@dataclass
class IngestPlan:
    """Plan for .scope files to be created."""
    root: str
    scopes: List["PlannedScope"] = field(default_factory=list)
    index: Optional[ScopesIndex] = None
    graph_summary: str = ""
    history_summary: str = ""
    backtest_summary: str = ""
    # Structured data for discovery rendering
    graph: Optional[DependencyGraph] = None
    history: Optional[HistoryAnalysis] = None
    backtest_report: Optional[BacktestReport] = None
    virtual_scopes: List[ScopeConfig] = field(default_factory=list)
    total_repo_files: int = 0
    total_repo_tokens: int = 0


@dataclass
class PlannedScope:
    """A .scope file to be created."""
    directory: str  # Relative to root
    config: ScopeConfig
    confidence: float  # How confident we are in this scope boundary
    signals: List[str]  # What signals contributed to this scope


@dataclass
class VirtualScope:
    """A detected cross-cutting scope."""
    name: str
    hub_file: str
    files: List[str]
    cohesion: float
    directories_spanned: int
