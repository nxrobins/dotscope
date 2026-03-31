"""Compiled Retrieval data models."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RetrievalChunk:
    """A single embedding unit derived from AST-aware chunking."""
    chunk_id: int           # Index into the embedding matrix
    file_path: str          # Relative to repo root
    start_line: int
    end_line: int
    content: str
    chunk_type: str         # "function", "class", "import_block", "module_preamble",
                            # "line_segment", "char_segment", "artifact"
    fqn: Optional[str] = None       # Fully qualified name if AST chunk (None for fallback)
    artifact_name: Optional[str] = None  # Non-None for context artifact chunks


@dataclass
class SearchResult:
    """A single retrieval hit before expansion."""
    file_path: str
    chunk: RetrievalChunk
    dense_score: float      # Cosine similarity (0.0 if no embeddings)
    bm25_score: float       # BM25 keyword score
    rrf_score: float        # Fused score
    recency_adjusted: float = 0.0  # After Stage 2 re-ranking


@dataclass
class ExpandedContext:
    """Dependency neighborhood attached to a search hit."""
    network_consumers: List[str] = field(default_factory=list)
    network_providers: List[str] = field(default_factory=list)
    npmi_companions: List[str] = field(default_factory=list)
    test_companions: List[str] = field(default_factory=list)


@dataclass
class FlattenedAbstraction:
    """A called function's source, resolved cross-file."""
    call_name: str
    origin_file: str
    source_code: str
    lock_status: str        # "unlocked", "exclusive_locked", "shared_locked"
    scope_crossing: str     # "same_file", "cross_file", "cross_scope"


@dataclass
class SearchBundle:
    """A search hit enriched with expansion and flattening. Internal only.
    Converted to ResolvedScope before reaching the agent."""
    file_path: str
    score: float
    content: str
    expanded: ExpandedContext = field(default_factory=ExpandedContext)
    abstractions: List[FlattenedAbstraction] = field(default_factory=list)


@dataclass
class VectorIndex:
    """Metadata for the stored embedding index."""
    model_name: str
    dimensions: int
    file_count: int
    chunk_count: int
    built_at: str                    # ISO timestamp
    last_vector_update_commit: str   # Git HEAD at last incremental or full update
