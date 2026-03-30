"""Core data models: the static architecture of a codebase."""

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
    total_repo_tokens: int = 0

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
    file_scores: Dict[str, float] = field(default_factory=dict)

    def merge(self, other: "ResolvedScope") -> "ResolvedScope":
        """Merge two resolved scopes (union)."""
        seen = set(self.files)
        merged_files = list(self.files)
        for f in other.files:
            if f not in seen:
                merged_files.append(f)
                seen.add(f)

        # Merge file scores, keeping the higher score for duplicates
        merged_scores = dict(self.file_scores)
        for f, s in other.file_scores.items():
            merged_scores[f] = max(merged_scores.get(f, 0.0), s)

        ctx_parts = [p for p in [self.context, other.context] if p]
        return ResolvedScope(
            files=merged_files,
            context="\n\n".join(ctx_parts),
            token_estimate=self.token_estimate + other.token_estimate,
            scope_chain=list(dict.fromkeys(self.scope_chain + other.scope_chain)),
            truncated=self.truncated or other.truncated,
            file_scores=merged_scores,
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
        ctx_parts = [p for p in [self.context, other.context] if p]
        return ResolvedScope(
            files=[f for f in self.files if f in other_set],
            context="\n\n".join(ctx_parts),
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


# ---------------------------------------------------------------------------
# AST analysis models
# ---------------------------------------------------------------------------

@dataclass
class ResolvedImport:
    """A single import statement, resolved to its structural meaning."""
    raw: str
    module: str = ""                       # Top-level module (e.g., "auth")
    resolved_path: Optional[str] = None    # Target file path, or None if external
    names: List[str] = field(default_factory=list)
    is_relative: bool = False
    is_star: bool = False
    is_conditional: bool = False
    is_type_only: bool = False             # Inside TYPE_CHECKING block
    line: int = 0


@dataclass
class ExportedSymbol:
    """A symbol exported by a module."""
    name: str
    kind: str  # "function", "class", "constant", "variable"
    is_public: bool = True


@dataclass
class ClassInfo:
    """Structural summary of a class definition."""
    name: str
    bases: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    method_count: int = 0
    decorators: List[str] = field(default_factory=list)
    is_abstract: bool = False
    is_public: bool = True
    line: int = 0


@dataclass
class FunctionInfo:
    """Structural summary of a function definition."""
    name: str
    params: List[str] = field(default_factory=list)
    arg_count: int = 0
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    is_public: bool = True
    is_async: bool = False
    complexity: int = 0                    # Count of if/for/while/try in body
    line: int = 0


@dataclass
class NetworkEndpoint:
    """A backend route definition (the Provider)."""
    method: str          # "GET", "POST", "PUT", "DELETE", "ALL"
    raw_path: str        # "/api/users/{user_id}"
    regex_path: str      # "^/api/users/[^/]+$"
    handler_name: str    # The function name handling the route
    file: str = ""       # File path where this endpoint lives


@dataclass
class NetworkConsumer:
    """A frontend HTTP call (the Consumer)."""
    method: str          # "GET", "POST", etc. ("GET" default for fetch)
    raw_path: str        # "/api/users/${id}" or string literal
    regex_path: str = "" # JS ${var} → [^/]+ regex, same language as Python
    file: str = ""       # File path where this call lives


@dataclass
class FileAnalysis:
    """Complete structural analysis of a single source file."""
    path: str
    language: str
    imports: List[ResolvedImport] = field(default_factory=list)
    exports: List[ExportedSymbol] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    decorators_used: List[str] = field(default_factory=list)  # All unique decorators
    network_endpoints: List[NetworkEndpoint] = field(default_factory=list)
    network_consumers: List[NetworkConsumer] = field(default_factory=list)
    is_init: bool = False                  # True for __init__.py
    reexports: List[str] = field(default_factory=list)  # Imported then re-exported
    node_count: int = 0                    # Total AST nodes (complexity proxy)
    docstring: Optional[str] = None
    all_list: Optional[List[str]] = None
    is_entry_point: bool = False

    @property
    def public_api(self) -> List[str]:
        if self.all_list is not None:
            return self.all_list
        names = []
        for cls in self.classes:
            if cls.is_public:
                names.append(cls.name)
        for fn in self.functions:
            if fn.is_public:
                names.append(fn.name)
        for exp in self.exports:
            if exp.is_public and exp.name not in names:
                names.append(exp.name)
        return names

    @property
    def import_paths(self) -> List[str]:
        return [i.resolved_path for i in self.imports if i.resolved_path]


# Keep ModuleAPI as alias for backward compatibility during migration
ModuleAPI = FileAnalysis


# ---------------------------------------------------------------------------
# Graph dataclasses (data only, no builder functions)
# ---------------------------------------------------------------------------

@dataclass
class FileNode:
    """A file in the dependency graph."""
    path: str  # Relative to root
    language: str
    imports: List[str] = field(default_factory=list)
    imported_by: List[str] = field(default_factory=list)
    api: Optional[ModuleAPI] = None


@dataclass
class ModuleBoundary:
    """A detected module boundary (candidate scope)."""
    directory: str
    files: List[str] = field(default_factory=list)
    internal_edges: int = 0
    external_edges: int = 0
    external_deps: List[str] = field(default_factory=list)
    depended_on_by: List[str] = field(default_factory=list)
    cohesion: float = 0.0
    churn: int = 0
    hotspot_files: List[str] = field(default_factory=list)


@dataclass
class DependencyGraph:
    """Full dependency graph of a codebase."""
    root: str
    files: Dict[str, FileNode] = field(default_factory=dict)
    edges: List[tuple] = field(default_factory=list)
    modules: List[ModuleBoundary] = field(default_factory=list)
    apis: Dict[str, ModuleAPI] = field(default_factory=dict)
    # Network contract edges (polyglot context)
    network_edges: Dict[str, Dict[str, list]] = field(default_factory=dict)
    # { provider_file: { consumer_file: [NetworkEndpoint] } }
    reverse_network_edges: Dict[str, List[str]] = field(default_factory=dict)
    # { consumer_file: [provider_file, ...] } — O(1) reverse lookup


@dataclass
class ConventionNode:
    """A file's membership in a convention, with any rule violations."""
    name: str          # Convention name, e.g. "REST Controller"
    file_path: str
    target_name: str   # Class or function name
    violations: List[str] = field(default_factory=list)
    matched_by: List[str] = field(default_factory=list)  # Which criteria matched
