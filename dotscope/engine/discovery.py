"""Discover repo roots, tracked scopes, and runtime-effective scope views."""


import os
from typing import List, Optional, Tuple

from ..engine.constants import SKIP_DIRS
from ..models import ScopeConfig, ScopesIndex




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
    from ..engine.parser import parse_scopes_index

    index_path = os.path.join(root, ".scopes")
    if os.path.isfile(index_path):
        return parse_scopes_index(index_path)
    return None


def load_resolution_index(root: str) -> Optional[ScopesIndex]:
    """Load the merged tracked + runtime index used for live resolution."""
    from dotscope.engine.runtime_overlay import load_effective_index

    return load_effective_index(root)


def find_scope(name_or_path: str, root: Optional[str] = None) -> Optional[ScopeConfig]:
    """Resolve a scope by name (from index), path, or directory.

    Resolution order:
    1. If name_or_path is a file path ending in .scope, parse it directly
    2. If name_or_path is a directory containing .scope, parse that
    3. Look up in .scopes index by name
    4. Look for name_or_path/.scope relative to root
    """
    from ..engine.parser import parse_scope_file

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


def find_resolution_scope(
    name_or_path: str,
    root: Optional[str] = None,
) -> Optional[ScopeConfig]:
    """Resolve a scope using runtime overlay first, then tracked fallback."""
    from dotscope.engine.runtime_overlay import find_effective_scope

    return find_effective_scope(name_or_path, root=root)


def find_resolution_scope_with_source(
    name_or_path: str,
    root: Optional[str] = None,
) -> Tuple[Optional[ScopeConfig], Optional[str]]:
    """Resolve a scope plus its source: runtime overlay or tracked snapshot."""
    from dotscope.engine.runtime_overlay import find_effective_scope_with_source

    return find_effective_scope_with_source(name_or_path, root=root)


def load_resolution_scopes(root: str) -> List[Tuple[str, ScopeConfig, str]]:
    """Load every live scope config, preferring runtime overlay entries."""
    from dotscope.engine.runtime_overlay import load_effective_scope_configs

    return load_effective_scope_configs(root)
