"""Structured context parsing and querying.

Convention: ## Section Name headers within a context block create named sections.
Agents can query specific sections (e.g., "gotchas", "invariants").
"""


import re
from typing import Optional

from ..models import StructuredContext


def parse_context(raw: str) -> StructuredContext:
    """Parse a context string into a StructuredContext with optional sections.

    Sections are delimited by ## headers within the context block:
        ## Invariants
        Some invariant text...

        ## Gotchas
        Watch out for...

    If no ## headers are found, the entire string is the raw context with no sections.
    """
    if not raw or not raw.strip():
        return StructuredContext(raw="", sections={})

    raw = raw.strip()
    sections: dict[str, str] = {}

    # Split on ## headers
    parts = re.split(r"^##\s+(.+)$", raw, flags=re.MULTILINE)

    # parts[0] is text before any header (preamble)
    # Then alternating: header_name, content, header_name, content, ...
    if len(parts) <= 1:
        # No sections found — the whole thing is raw context
        return StructuredContext(raw=raw, sections={})

    preamble = parts[0].strip()
    i = 1
    while i < len(parts) - 1:
        section_name = parts[i].strip()
        section_content = parts[i + 1].strip()
        sections[section_name] = section_content
        i += 2

    # If there's a preamble, add it as a special section
    if preamble:
        sections["_preamble"] = preamble

    return StructuredContext(raw=raw, sections=sections)


def query_context(ctx: Optional[StructuredContext], section: Optional[str] = None) -> str:
    """Query context, optionally filtering to a named section."""
    if ctx is None:
        return ""
    return ctx.query(section)
