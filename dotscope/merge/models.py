"""AST Merge Driver data models.

Strict line-level representations for lossless semantic merging.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class MutationType(Enum):
    ADD = "add"
    MODIFY = "modify"
    REMOVE = "remove"


class NodeType(Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    IMPORT = "import"
    ASSIGNMENT = "assignment"
    MODULE = "module"


@dataclass
class SourceSegment:
    """An exact range in a source file, including visual boundaries."""
    start_line: int            # 1-indexed inclusive
    end_line: int              # 1-indexed inclusive (AST end)
    visual_end_line: int       # Includes trailing blank lines
    text: str                  # Exact source text of this segment


@dataclass
class ASTMutation:
    """A single structural change detected between ancestor and agent."""
    type: MutationType
    node_type: NodeType
    fqn: str                   # Fully qualified name (e.g., "MyClass.my_method")
    ancestor_segment: Optional[SourceSegment] = None   # Before state (None for ADDs)
    agent_segment: Optional[SourceSegment] = None      # After state (None for REMOVEs)
    dependencies: List[str] = field(default_factory=list)  # FQNs this mutation depends on


@dataclass
class MergeHalt:
    """Signals that automatic merge cannot proceed."""
    reason: str
    conflicting_mutations: List[ASTMutation] = field(default_factory=list)
    agent_a_fqns: List[str] = field(default_factory=list)
    agent_b_fqns: List[str] = field(default_factory=list)


@dataclass
class MergeResult:
    """Result of a 3-way merge attempt."""
    success: bool
    merged_source: str = ""
    halts: List[MergeHalt] = field(default_factory=list)
    mutations_applied: int = 0
    imports_resolved: int = 0
