"""Intent data models: the human rulebook for enforcement."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Severity(Enum):
    GUARD = "guard"  # Blocks commit. Protective wall.
    NUDGE = "nudge"  # Prints warning. Does not block. Course correction.
    NOTE = "note"    # Informational.
    HOLD = "hold"    # Backwards compat — treated same as GUARD

    @property
    def blocks_commit(self) -> bool:
        return self.value in ("guard", "hold")


class CheckCategory(Enum):
    BOUNDARY = "boundary_violation"
    CONTRACT = "implicit_contract"
    ANTIPATTERN = "anti_pattern"
    DIRECTION = "dependency_direction"
    STABILITY = "stability_concern"
    INTENT = "architectural_intent"
    CONVENTION = "convention_violation"
    VOICE = "voice_violation"


@dataclass
class IntentDirective:
    """A declared architectural intent."""
    directive: str  # "decouple", "deprecate", "freeze", "consolidate"
    modules: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    reason: str = ""
    replacement: Optional[str] = None
    target: Optional[str] = None
    set_by: str = "developer"
    set_at: str = ""
    id: str = ""  # Auto-generated slug


@dataclass
class Constraint:
    """A single constraint surfaced during resolve_scope (prophylactic mode)."""
    category: str  # "contract", "anti_pattern", "dependency_boundary", "stability", "intent"
    message: str
    file: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class ProposedFix:
    """A machine-generated fix proposal the agent can apply."""
    file: str
    reason: str
    predicted_sections: List[str] = field(default_factory=list)
    proposed_diff: Optional[str] = None  # Unified diff
    confidence: float = 0.5


@dataclass
class CheckResult:
    """A single check finding."""
    passed: bool
    category: CheckCategory
    severity: Severity
    message: str
    detail: str = ""
    file: Optional[str] = None
    suggestion: Optional[str] = None
    proposed_fix: Optional[ProposedFix] = None
    can_acknowledge: bool = False
    acknowledge_id: Optional[str] = None


@dataclass
class CheckReport:
    """Aggregate report from all checks against a diff."""
    passed: bool
    results: List[CheckResult] = field(default_factory=list)
    files_checked: int = 0
    checks_run: int = 0

    @property
    def guards(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed and r.severity.blocks_commit]

    @property
    def nudges(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.NUDGE]

    @property
    def notes(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.NOTE]

    @property
    def holds(self) -> List[CheckResult]:
        """Backwards compat alias for guards."""
        return self.guards


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class ContextExhaustionError(Exception):
    """Token budget cannot satisfy required assertions."""

    def __init__(
        self,
        assertion_type: str,
        detail: str,
        file: Optional[str] = None,
        file_tokens: int = 0,
        budget: int = 0,
        tokens_used: int = 0,
        reason: str = "",
        suggestion: str = "",
    ):
        self.assertion_type = assertion_type
        self.detail = detail
        self.file = file
        self.file_tokens = file_tokens
        self.budget = budget
        self.tokens_used = tokens_used
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(detail)

    def to_dict(self) -> dict:
        return {
            "error": "context_exhaustion",
            "assertion_failed": {
                "type": self.assertion_type,
                "detail": self.detail,
                "file": self.file,
                "file_tokens": self.file_tokens,
                "budget": self.budget,
                "reason": self.reason,
            },
            "suggestion": self.suggestion,
        }


@dataclass
class Assertion:
    """A single architectural assertion."""
    scope: str = "*"  # Scope name or "*" for all
    ensure_includes: List[str] = field(default_factory=list)
    ensure_context_contains: List[str] = field(default_factory=list)
    ensure_constraints: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Near-miss dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WarningPair:
    """An extracted (anti_pattern, safe_pattern) pair from scope context."""
    anti_pattern: str
    safe_pattern: str
    context_line: str
    scope: str


@dataclass
class NearMiss:
    """A detected near-miss event."""
    scope: str
    event: str
    context_used: str
    potential_impact: str


# ---------------------------------------------------------------------------
# Convention dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConventionRule:
    """A structural convention: discovered or hand-authored."""
    name: str
    source: str = "discovered"  # "discovered" | "hand_authored"
    match_criteria: Dict[str, list] = field(default_factory=dict)  # {"any_of": [...], "all_of": [...]}
    rules: Dict[str, object] = field(default_factory=dict)  # {"prohibited_imports": [...], ...}
    description: str = ""
    compliance: float = 1.0
    last_checked: Optional[str] = None


# ---------------------------------------------------------------------------
# Voice dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredVoice:
    """Coding style profile: discovered from codebase or prescriptive defaults."""
    mode: str = "adaptive"  # "prescriptive" | "adaptive"
    rules: Dict[str, str] = field(default_factory=dict)
    stats: Dict[str, float] = field(default_factory=dict)
    enforce: Dict[str, object] = field(default_factory=dict)


@dataclass
class CanonicalExample:
    """A representative file for a convention's coding style."""
    file_path: str = ""
    snippet: Optional[str] = None
