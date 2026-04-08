"""Token estimation for scope files and resolved contexts.

Uses tiktoken if available, otherwise falls back to len(text) // 4.
"""


import os
from typing import List
from ..ux.textio import read_repo_text

# Try tiktoken for accurate counts, fall back to approximation
try:
    import tiktoken

    _encoder = tiktoken.encoding_for_model("gpt-4")

    def estimate_tokens(text: str) -> int:
        """Estimate token count using tiktoken."""
        return len(_encoder.encode(text, allowed_special="all"))

except ImportError:

    def estimate_tokens(text: str) -> int:
        """Estimate token count (~4 chars per token for English)."""
        return len(text) // 4


def estimate_file_tokens(path: str) -> int:
    """Read a file and estimate its token count."""
    try:
        return estimate_tokens(read_repo_text(path).text)
    except (OSError, IOError):
        return 0


def estimate_scope_tokens(files: List[str]) -> int:
    """Estimate total tokens across a list of files."""
    return sum(estimate_file_tokens(f) for f in files)


def estimate_context_tokens(context: str) -> int:
    """Estimate tokens for a context string."""
    if not context:
        return 0
    return estimate_tokens(context)


def file_size_bytes(path: str) -> int:
    """Get file size in bytes, 0 if not accessible."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
