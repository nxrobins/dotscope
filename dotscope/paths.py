"""Shared path helpers — normalize, relative, exists checks."""


import os
from typing import Optional


def normalize(base: str, rel_path: str) -> str:
    """Join and normalize a base + relative path."""
    return os.path.normpath(os.path.join(base, rel_path))


def make_relative(abs_path: str, root: Optional[str]) -> str:
    """Make a path relative to root, falling back to absolute."""
    if root:
        try:
            return os.path.relpath(abs_path, root)
        except ValueError:
            pass
    return abs_path


def path_exists(base: str, rel_path: str) -> bool:
    """Check if a path (possibly with trailing /) exists."""
    full = normalize(base, rel_path)
    return os.path.exists(full.rstrip("/"))


def strip_inline_comment(text: str) -> str:
    """Strip trailing '# comment' from a path or value string."""
    parts = text.split("#", 1)
    return parts[0].strip()
