"""Core data models for dotscope."""


from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StructuredContext:
    """Context with optional named sections (## headers within the context block)."""

    raw: str
    sections: Dict[str, str] = field(default_factory=dict)

    def query(self, section: Optional[str] = None) -> str:
        if section is None:
            return self.raw
        key = section.lower().strip()
        for name, content in self.sections.items():
            if name.lower() == key:
                return content
        return ""

    def __str__(self) -> str:
        return self.raw


@dataclass
class ScopeConfig:
    """Parsed .scope file."""

    path: str  # Absolute path to the .scope file
    description: str
    includes: List[str] = field(default_factory=list)
    excludes: List[str] = field(default_factory=list)
    context: Optional[StructuredContext] = None
    related: List[str] = field(default_factory=list)
    owners: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    tokens_estimate: Optional[int] = None

    @property
    def context_str(self) -> str:
        if self.context is None:
            return ""
        return self.context.raw

    @property
    def directory(self) -> str:
        """Directory containing this .scope file."""
        import os

        return os.path.dirname(self.path)


@dataclass
class ScopeEntry:
    """Entry in the .scopes index file."""

    name: str
    path: str
    keywords: List[str] = field(default_factory=list)
    description: Optional[str] = None


@dataclass
class ScopesIndex:
    """Parsed .scopes index file (repo root)."""

    version: int = 1
    scopes: Dict[str, ScopeEntry] = field(default_factory=dict)
    defaults: Dict[str, object] = field(default_factory=dict)

    @property
    def max_tokens(self) -> int:
        return int(self.defaults.get("max_tokens", 8000))

    @property
    def include_related(self) -> bool:
        return bool(self.defaults.get("include_related", False))


@dataclass
class ResolvedScope:
    """Result of resolving a scope to concrete files."""

    files: List[str] = field(default_factory=list)
    context: str = ""
    token_estimate: int = 0
    scope_chain: List[str] = field(default_factory=list)
    truncated: bool = False
    excluded_files: List[str] = field(default_factory=list)

    def merge(self, other: "ResolvedScope") -> "ResolvedScope":
        """Merge two resolved scopes (union)."""
        seen = set(self.files)
        merged_files = list(self.files)
        for f in other.files:
            if f not in seen:
                merged_files.append(f)
                seen.add(f)

        ctx_parts = [p for p in [self.context, other.context] if p]
        return ResolvedScope(
            files=merged_files,
            context="\n\n".join(ctx_parts),
            token_estimate=self.token_estimate + other.token_estimate,
            scope_chain=list(dict.fromkeys(self.scope_chain + other.scope_chain)),
            truncated=self.truncated or other.truncated,
        )

    def subtract(self, other: "ResolvedScope") -> "ResolvedScope":
        """Remove files present in other scope."""
        other_set = set(other.files)
        return ResolvedScope(
            files=[f for f in self.files if f not in other_set],
            context=self.context,
            token_estimate=0,  # recalculated after
            scope_chain=self.scope_chain,
            truncated=self.truncated,
        )

    def intersect(self, other: "ResolvedScope") -> "ResolvedScope":
        """Keep only files present in both scopes."""
        other_set = set(other.files)
        return ResolvedScope(
            files=[f for f in self.files if f in other_set],
            context=self.context,
            token_estimate=0,
            scope_chain=list(dict.fromkeys(self.scope_chain + other.scope_chain)),
            truncated=self.truncated or other.truncated,
        )


@dataclass
class TokenBudget:
    """Token budget for progressive file loading."""

    max_tokens: int
    context_reserved: int = 0
    remaining: int = 0

    def __post_init__(self):
        self.remaining = self.max_tokens - self.context_reserved


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
