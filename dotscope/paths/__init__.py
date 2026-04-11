"""Shared path helpers — canonical repo-relative paths, relative output, exists checks."""


import os
import posixpath
from typing import Optional


def strip_inline_comment(text: str) -> str:
    """Strip trailing '# comment' from a path or value string."""
    parts = text.split("#", 1)
    return parts[0].strip()


def canonicalize_separators(path: str) -> str:
    """Convert path separators to POSIX style for repo-internal storage."""
    return path.replace("\\", "/")


def normalize_relative_path(path: str, preserve_trailing: Optional[bool] = None) -> str:
    """Normalize a repo-relative path to POSIX separators.

    This keeps dotscope's internal path representation stable across platforms.
    """
    raw = strip_inline_comment(path).strip()
    if not raw:
        return ""

    trailing = preserve_trailing if preserve_trailing is not None else raw.endswith(("/", "\\"))
    normalized = posixpath.normpath(canonicalize_separators(raw))
    if normalized == ".":
        normalized = ""

    if trailing and normalized and not normalized.endswith("/"):
        normalized += "/"

    return normalized


def normalize_directory_include(path: str) -> str:
    """Normalize a directory include and preserve its trailing slash."""
    normalized = normalize_relative_path(path, preserve_trailing=True)
    if normalized and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def normalize_scope_ref(path: str) -> str:
    """Normalize a related/index scope path."""
    return normalize_relative_path(path, preserve_trailing=False)


def normalize(base: str, rel_path: str) -> str:
    """Join and normalize a base + relative path."""
    clean_path = strip_inline_comment(rel_path)
    os_path = canonicalize_separators(clean_path).replace("/", os.sep)
    return os.path.normpath(os.path.join(base, os_path))


def make_relative(abs_path: str, root: Optional[str]) -> str:
    """Make a path relative to root, falling back to absolute."""
    if root:
        try:
            return normalize_relative_path(os.path.relpath(abs_path, root))
        except ValueError:
            pass
    return canonicalize_separators(abs_path)


def path_exists(base: str, rel_path: str) -> bool:
    """Check if a path (possibly with trailing /) exists."""
    full = normalize(base, rel_path)
    return os.path.exists(full.rstrip("/\\"))


def scope_storage_key(scope_path: str, root: Optional[str] = None) -> str:
    """Build a canonical repo-relative key for a scope file path."""
    candidate = scope_path
    if root and os.path.isabs(scope_path):
        try:
            candidate = os.path.relpath(scope_path, root)
        except ValueError:
            candidate = scope_path
    return normalize_scope_ref(candidate)
