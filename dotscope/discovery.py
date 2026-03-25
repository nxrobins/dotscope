"""Discover repo roots, .scope files, and .scopes index files."""


import os
from typing import List, Optional

from .constants import SKIP_DIRS
from .models import ScopeConfig, ScopesIndex


def find_repo_root(start_dir: Optional[str] = None) -> Optional[str]:
    """Walk up from start_dir looking for .scopes, .git, or a .scope file.

    Returns the directory containing the marker, or None.
    """
    current = os.path.abspath(start_dir or os.getcwd())

    while True:
        if os.path.isfile(os.path.join(current, ".scopes")):
            return current
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        if os.path.isfile(os.path.join(current, ".scope")):
            return current

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return None


def find_all_scopes(root: str) -> List[str]:
    """Find all .scope files under root, returning absolute paths.

    Skips common directories that should never be scanned.
    """
    scope_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        if ".scope" in filenames:
            scope_files.append(os.path.join(dirpath, ".scope"))

    return sorted(scope_files)


def load_index(root: str) -> Optional[ScopesIndex]:
    """Load .scopes index from repo root, if it exists."""
    from .parser import parse_scopes_index

    index_path = os.path.join(root, ".scopes")
    if os.path.isfile(index_path):
        return parse_scopes_index(index_path)
    return None


def find_scope(name_or_path: str, root: Optional[str] = None) -> Optional[ScopeConfig]:
    """Resolve a scope by name (from index), path, or directory.

    Resolution order:
    1. If name_or_path is a file path ending in .scope, parse it directly
    2. If name_or_path is a directory containing .scope, parse that
    3. Look up in .scopes index by name
    4. Look for name_or_path/.scope relative to root
    """
    from .parser import parse_scope_file

    # Direct .scope file path
    if name_or_path.endswith(".scope") and os.path.isfile(name_or_path):
        return parse_scope_file(name_or_path)

    # Absolute directory containing .scope
    if os.path.isdir(name_or_path):
        scope_path = os.path.join(name_or_path, ".scope")
        if os.path.isfile(scope_path):
            return parse_scope_file(scope_path)

    # Need root for index and relative lookups
    if root is None:
        root = find_repo_root()
    if root is None:
        return None

    # Check .scopes index
    index = load_index(root)
    if index and name_or_path in index.scopes:
        entry = index.scopes[name_or_path]
        scope_path = os.path.join(root, entry.path)
        if os.path.isfile(scope_path):
            return parse_scope_file(scope_path)

    # Try as relative directory
    candidate = os.path.join(root, name_or_path, ".scope")
    if os.path.isfile(candidate):
        return parse_scope_file(candidate)

    # Try as relative path to .scope
    candidate = os.path.join(root, name_or_path)
    if candidate.endswith(".scope") and os.path.isfile(candidate):
        return parse_scope_file(candidate)

    return None
