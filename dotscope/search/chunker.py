"""AST-aware chunking with graceful degradation.

Three tiers:
  Tier 1 — AST-Aware: function/class/method boundaries from FileAnalysis
  Tier 2 — Line-Based: fallback for AST parse failure (syntax errors)
  Tier 3 — Character-Based: fallback for minified/bundled code

Chunks carry FQNs (Tier 1 only) for abstraction flattening and lock
checking. Tier 2/3 chunks have fqn=None and are ineligible for flattening.
"""

import os
from typing import List, Optional

from ..models import FileAnalysis
from ..engine.tokens import estimate_tokens
from .models import RetrievalChunk

# Threshold: files with average line length above this are minified/bundled
MINIFIED_AVG_LINE_LENGTH = 500

# Fallback chunk parameters
LINE_CHUNK_SIZE = 100        # Lines per chunk
LINE_CHUNK_OVERLAP = 10      # Overlapping lines between adjacent chunks
CHAR_CHUNK_SIZE = 1500       # Characters per chunk
CHAR_CHUNK_OVERLAP = 200     # Overlapping characters between adjacent chunks

# Maximum tokens per AST chunk before sub-chunking
MAX_CHUNK_TOKENS = 1500

# Global chunk ID counter (reset per build_vector_index call)
_chunk_counter = 0


def _next_chunk_id() -> int:
    global _chunk_counter
    cid = _chunk_counter
    _chunk_counter += 1
    return cid


def reset_chunk_counter() -> None:
    global _chunk_counter
    _chunk_counter = 0


def chunk_file(
    file_path: str,
    analysis: Optional[FileAnalysis],
    source: str,
) -> List[RetrievalChunk]:
    """Produce embedding-optimized chunks using a three-tier strategy."""
    if not source.strip():
        return []

    if _is_minified(source):
        return _chunk_chars(file_path, source)
    elif analysis is not None:
        return _chunk_ast(file_path, analysis, source)
    else:
        return _chunk_lines(file_path, source)


def chunk_artifact(
    artifact_name: str,
    artifact_path: str,
    content: str,
) -> List[RetrievalChunk]:
    """Chunk a context artifact (schema, API spec, infra config).

    Always uses line-based chunking since artifacts are typically SQL,
    YAML, proto, or markdown — not Python/JS.
    """
    if not content.strip():
        return []

    lines = content.splitlines(keepends=True)
    chunks = []

    for start in range(0, len(lines), LINE_CHUNK_SIZE - LINE_CHUNK_OVERLAP):
        end = min(start + LINE_CHUNK_SIZE, len(lines))
        chunk_text = "".join(lines[start:end])
        if not chunk_text.strip():
            continue
        chunks.append(RetrievalChunk(
            chunk_id=_next_chunk_id(),
            file_path=artifact_path,
            start_line=start + 1,
            end_line=end,
            content=chunk_text,
            chunk_type="artifact",
            artifact_name=artifact_name,
        ))
        if end >= len(lines):
            break

    return chunks


# ---------------------------------------------------------------------------
# Tier 1: AST-Aware Chunking
# ---------------------------------------------------------------------------

def _chunk_ast(
    file_path: str,
    analysis: FileAnalysis,
    source: str,
) -> List[RetrievalChunk]:
    """Chunk using AST boundaries from FileAnalysis."""
    lines = source.splitlines(keepends=True)
    chunks = []
    claimed_lines = set()

    # Import block
    if analysis.imports:
        import_lines = []
        for imp in analysis.imports:
            if imp.line > 0 and imp.line <= len(lines):
                import_lines.append(imp.line)
        if import_lines:
            start = min(import_lines)
            end = max(import_lines)
            text = "".join(lines[start - 1:end])
            if text.strip():
                chunks.append(RetrievalChunk(
                    chunk_id=_next_chunk_id(),
                    file_path=file_path,
                    start_line=start,
                    end_line=end,
                    content=text,
                    chunk_type="import_block",
                    fqn="<imports>",
                ))
                claimed_lines.update(range(start, end + 1))

    # Functions
    for fn in analysis.functions:
        if fn.line > 0:
            start = fn.line
            end = getattr(fn, "end_line", fn.line + 10)
            if end <= 0:
                end = min(start + 20, len(lines))
            text = "".join(lines[start - 1:min(end, len(lines))])
            if text.strip():
                chunk = RetrievalChunk(
                    chunk_id=_next_chunk_id(),
                    file_path=file_path,
                    start_line=start,
                    end_line=end,
                    content=text,
                    chunk_type="function",
                    fqn=fn.name,
                )
                # Sub-chunk if too large
                if estimate_tokens(text) > MAX_CHUNK_TOKENS:
                    chunks.extend(_sub_chunk_lines(file_path, text, start, fn.name))
                else:
                    chunks.append(chunk)
                claimed_lines.update(range(start, end + 1))

    # Classes (one chunk per class, methods get their own chunks)
    for cls in analysis.classes:
        if cls.line > 0:
            start = cls.line
            end = getattr(cls, "end_line", cls.line + 20)
            if end <= 0:
                end = min(start + 30, len(lines))

            # Class preamble (up to first method)
            first_method_line = end
            for method_name in cls.methods:
                # Find method line in the source (approximate)
                for i in range(start, min(end, len(lines))):
                    if f"def {method_name}" in lines[i]:
                        first_method_line = min(first_method_line, i + 1)
                        break

            if first_method_line > start:
                preamble_text = "".join(lines[start - 1:first_method_line - 1])
                if preamble_text.strip():
                    chunks.append(RetrievalChunk(
                        chunk_id=_next_chunk_id(),
                        file_path=file_path,
                        start_line=start,
                        end_line=first_method_line - 1,
                        content=preamble_text,
                        chunk_type="class",
                        fqn=cls.name,
                    ))

            claimed_lines.update(range(start, end + 1))

    # Module preamble: code between imports and first def/class
    if chunks:
        first_entity_line = min(
            (c.start_line for c in chunks if c.chunk_type in ("function", "class")),
            default=len(lines) + 1,
        )
        last_import_line = max(
            (c.end_line for c in chunks if c.chunk_type == "import_block"),
            default=0,
        )
        if last_import_line + 1 < first_entity_line:
            preamble_text = "".join(lines[last_import_line:first_entity_line - 1])
            if preamble_text.strip():
                chunks.append(RetrievalChunk(
                    chunk_id=_next_chunk_id(),
                    file_path=file_path,
                    start_line=last_import_line + 1,
                    end_line=first_entity_line - 1,
                    content=preamble_text,
                    chunk_type="module_preamble",
                ))

    # Remaining unclaimed lines → line-based
    unclaimed = [i for i in range(1, len(lines) + 1) if i not in claimed_lines]
    if unclaimed:
        # Group into contiguous ranges
        ranges = []
        range_start = unclaimed[0]
        for i in range(1, len(unclaimed)):
            if unclaimed[i] != unclaimed[i - 1] + 1:
                ranges.append((range_start, unclaimed[i - 1]))
                range_start = unclaimed[i]
        ranges.append((range_start, unclaimed[-1]))

        for rstart, rend in ranges:
            text = "".join(lines[rstart - 1:rend])
            if text.strip():
                chunks.append(RetrievalChunk(
                    chunk_id=_next_chunk_id(),
                    file_path=file_path,
                    start_line=rstart,
                    end_line=rend,
                    content=text,
                    chunk_type="line_segment",
                ))

    return chunks


def _sub_chunk_lines(
    file_path: str, text: str, base_line: int, fqn: str
) -> List[RetrievalChunk]:
    """Split a large AST chunk into sub-chunks at line boundaries."""
    lines = text.splitlines(keepends=True)
    chunks = []
    for start in range(0, len(lines), LINE_CHUNK_SIZE - LINE_CHUNK_OVERLAP):
        end = min(start + LINE_CHUNK_SIZE, len(lines))
        sub_text = "".join(lines[start:end])
        if sub_text.strip():
            chunks.append(RetrievalChunk(
                chunk_id=_next_chunk_id(),
                file_path=file_path,
                start_line=base_line + start,
                end_line=base_line + end - 1,
                content=sub_text,
                chunk_type="function",
                fqn=fqn,
            ))
        if end >= len(lines):
            break
    return chunks


# ---------------------------------------------------------------------------
# Tier 2: Line-Based Fallback
# ---------------------------------------------------------------------------

def _chunk_lines(file_path: str, source: str) -> List[RetrievalChunk]:
    """Split source into fixed-size line segments with overlap."""
    lines = source.splitlines(keepends=True)
    chunks = []

    for start in range(0, len(lines), LINE_CHUNK_SIZE - LINE_CHUNK_OVERLAP):
        end = min(start + LINE_CHUNK_SIZE, len(lines))
        text = "".join(lines[start:end])
        if not text.strip():
            continue
        chunks.append(RetrievalChunk(
            chunk_id=_next_chunk_id(),
            file_path=file_path,
            start_line=start + 1,
            end_line=end,
            content=text,
            chunk_type="line_segment",
        ))
        if end >= len(lines):
            break

    return chunks


# ---------------------------------------------------------------------------
# Tier 3: Character-Based Fallback (minified/bundled code)
# ---------------------------------------------------------------------------

def _chunk_chars(file_path: str, source: str) -> List[RetrievalChunk]:
    """Split minified source at safe character boundaries."""
    chunks = []
    pos = 0

    while pos < len(source):
        end = min(pos + CHAR_CHUNK_SIZE, len(source))

        # Find a safe split boundary within the overlap zone
        if end < len(source):
            # Prefer: newline > semicolon > comma > space
            best = end
            for delim in ("\n", ";", ",", " "):
                idx = source.rfind(delim, pos + CHAR_CHUNK_SIZE - CHAR_CHUNK_OVERLAP, end)
                if idx > pos:
                    best = idx + 1
                    break
            end = best

        text = source[pos:end]
        if text.strip():
            # Approximate line numbers
            start_line = source[:pos].count("\n") + 1
            end_line = source[:end].count("\n") + 1
            chunks.append(RetrievalChunk(
                chunk_id=_next_chunk_id(),
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                content=text,
                chunk_type="char_segment",
            ))

        # Advance with overlap
        pos = max(pos + 1, end - CHAR_CHUNK_OVERLAP)

    return chunks


def _is_minified(source: str) -> bool:
    """True if average line length exceeds MINIFIED_AVG_LINE_LENGTH."""
    lines = source.splitlines()
    if not lines:
        return False
    avg = sum(len(line) for line in lines) / len(lines)
    return avg > MINIFIED_AVG_LINE_LENGTH
