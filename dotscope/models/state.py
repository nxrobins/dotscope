"""State data models: the persistent memory layer."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Observation layer models
# ---------------------------------------------------------------------------

@dataclass
class SessionLog:
    """Records a single scope resolution event (the prediction)."""
    session_id: str
    timestamp: float
    scope_expr: str
    task: Optional[str] = None
    predicted_files: List[str] = field(default_factory=list)
    context_hash: str = ""
    constraints_surfaced: List[str] = field(default_factory=list)


@dataclass
class ObservationLog:
    """Records what actually happened after a resolution (the outcome)."""
    commit_hash: str
    session_id: str
    actual_files_modified: List[str] = field(default_factory=list)
    predicted_not_touched: List[str] = field(default_factory=list)
    touched_not_predicted: List[str] = field(default_factory=list)
    recall: float = 0.0
    precision: float = 0.0
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Health models
# ---------------------------------------------------------------------------

@dataclass
class HealthIssue:
    """A single health issue found during scope analysis."""
    scope_path: str
    severity: str  # "error", "warning", "info"
    category: str  # "staleness", "coverage", "drift", "broken_path"
    message: str


@dataclass
class HealthReport:
    """Full health report across all scopes."""
    issues: List[HealthIssue] = field(default_factory=list)
    scopes_checked: int = 0
    directories_total: int = 0
    directories_covered: int = 0

    @property
    def coverage_pct(self) -> float:
        if self.directories_total == 0:
            return 100.0
        return (self.directories_covered / self.directories_total) * 100

    @property
    def errors(self) -> List[HealthIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[HealthIssue]:
        return [i for i in self.issues if i.severity == "warning"]


# ---------------------------------------------------------------------------
# Backtest models
# ---------------------------------------------------------------------------

@dataclass
class MissingSuggestion:
    """A file that should be added to a scope's includes."""
    path: str
    appearances: int
    would_improve_recall: bool = True


@dataclass
class BacktestResult:
    """Backtest result for a single scope."""
    scope_path: str
    total_commits: int = 0
    fully_covered: int = 0
    recall: float = 0.0
    missing_includes: List[MissingSuggestion] = field(default_factory=list)


@dataclass
class BacktestReport:
    """Full backtest report across all scopes."""
    results: List[BacktestResult] = field(default_factory=list)
    total_commits: int = 0
    overall_recall: float = 0.0


# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------

@dataclass
class BenchReport:
    # Token efficiency
    avg_tokens_resolved: int = 0
    avg_tokens_used: int = 0
    efficiency_ratio: float = 0.0

    # Hold rate
    total_commits: int = 0
    commits_with_holds: int = 0
    holds_acknowledged: int = 0
    effective_hold_rate: float = 0.0

    # Compilation speed
    resolve_median_ms: float = 0.0
    resolve_p95_ms: float = 0.0
    check_median_ms: float = 0.0
    check_p95_ms: float = 0.0

    # Scope health
    scopes_above_80_recall: int = 0
    total_scopes: int = 0
    stale_scopes: int = 0
    avg_observations: float = 0.0


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

@dataclass
class RegressionCase:
    """A frozen successful session used as a regression test."""
    id: str
    scope_expr: str
    budget: Optional[int] = None
    task: Optional[str] = None
    expected_files: List[str] = field(default_factory=list)
    expected_context_hash: str = ""
    actual_recall: float = 0.0
    timestamp: str = ""


@dataclass
class ReplayResult:
    """Result of replaying a regression case against current state."""
    case: RegressionCase
    new_files: List[str] = field(default_factory=list)
    new_context_hash: str = ""
    files_added: List[str] = field(default_factory=list)
    files_dropped: List[str] = field(default_factory=list)
    context_changed: bool = False
    is_regression: bool = False


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

@dataclass
class BisectionResult:
    """Root cause analysis of a bad agent session."""
    session_id: str
    files_that_mattered: List[str] = field(default_factory=list)
    files_that_didnt_help: List[str] = field(default_factory=list)
    context_sections_relevant: List[str] = field(default_factory=list)
    context_sections_irrelevant: List[str] = field(default_factory=list)
    constraints_honored: List[dict] = field(default_factory=list)
    constraints_violated: List[dict] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    diagnosis: str = ""  # "resolution_gap" | "constraint_gap" | "agent_ignored" | "context_conflict"
    recommendations: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

@dataclass
class SessionStats:
    """Raw stats accumulated during an MCP session."""
    scopes_resolved: int = 0
    tokens_served: int = 0
    tokens_available: int = 0
    context_fields_used: int = 0
    attribution_hints_served: int = 0
    health_warnings_surfaced: int = 0
    unique_scopes: Set[str] = field(default_factory=set)
    constraints_served: List[dict] = field(default_factory=list)
    started_at: Optional[str] = None
    last_activity: Optional[str] = None
    client_identifier: Optional[str] = None


# ---------------------------------------------------------------------------
# Counterfactual
# ---------------------------------------------------------------------------

@dataclass
class Counterfactual:
    """A bad thing that didn't happen because dotscope was there."""
    type: str  # "anti_pattern_avoided", "contract_honored", "intent_respected"
    description: str
    source: str  # Where the knowledge came from
    severity: str = "high"  # "high" or "medium"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

@dataclass
class FileUtilityScore:
    """Utility score for a single file, derived from observations."""
    path: str
    resolve_count: int = 0       # Sessions that included this file
    touch_count: int = 0         # Observations where this file was modified
    utility_ratio: float = 0.0   # touch_count / resolve_count
    last_touched: float = 0.0
    last_resolved: float = 0.0


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    """A machine-generated lesson from observation patterns."""
    trigger: str
    observation: str
    lesson_text: str
    confidence: float
    created: float
    source_sessions: List[str] = field(default_factory=list)
    acknowledged: bool = False


@dataclass
class ObservedInvariant:
    """An evidence-based boundary constraint."""
    boundary: str          # e.g., "auth -> payments"
    direction: str         # "no_import"
    held_since: str        # ISO date
    commit_count: int
    confidence: float
    violations: List[str] = field(default_factory=list)
