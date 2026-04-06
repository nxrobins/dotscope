"""Core resolution engine: .scope config → concrete file list.

Walks includes, applies excludes, follows related scopes with cycle detection.
"""


import fnmatch
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .constants import SKIP_DIRS
from .models import ResolvedScope, ScopeConfig
from .tokens import estimate_file_tokens, estimate_context_tokens

# Module-level cache: dir_path -> (mtime, file_list)
_dir_cache: Dict[str, Tuple[float, List[str]]] = {}


def clear_resolve_cache() -> None:
    """Invalidate the directory walk cache.

    Call from tests or when the filesystem is known to have changed.
    """
    _dir_cache.clear()


def resolve(
    config: ScopeConfig,
    follow_related: bool = True,
    max_depth: int = 3,
    root: Optional[str] = None,
) -> ResolvedScope:
    """Resolve a ScopeConfig to a concrete file list.

    Args:
        config: Parsed .scope configuration
        follow_related: Whether to follow related scope references
        max_depth: Maximum depth for related scope traversal
        root: Repository root (for resolving related scope paths)
    """
    return _resolve_inner(config, follow_related, max_depth, root, set(), 0)


def _resolve_inner(
    config: ScopeConfig,
    follow_related: bool,
    max_depth: int,
    root: Optional[str],
    _visited: Set[str],
    _depth: int,
) -> ResolvedScope:
    """Internal resolver with cycle detection state."""

    # Cycle detection
    abs_path = os.path.abspath(config.path)
    if abs_path in _visited:
        return ResolvedScope(scope_chain=[abs_path])
    _visited.add(abs_path)

    scope_dir = config.directory
    if root is None:
        from .paths.repo import find_repo_root
        root = find_repo_root(scope_dir) or scope_dir

    files = _collect_includes(config.includes, root)
    files = _apply_excludes(files, config.excludes, root)
    context = config.context_str
    file_tokens = sum(estimate_file_tokens(f) for f in files)
    context_tokens = estimate_context_tokens(context)

    result = ResolvedScope(
        files=files,
        context=context,
        token_estimate=file_tokens + context_tokens,
        scope_chain=[abs_path],
        truncated=False,
    )

    if follow_related and config.related and _depth < max_depth:
        for related_path in config.related:
            related_config = _load_related(related_path, scope_dir, root)
            if related_config is None:
                continue

            related_resolved = _resolve_inner(
                related_config,
                follow_related=True,
                max_depth=max_depth,
                root=root,
                _visited=_visited,
                _depth=_depth + 1,
            )
            result = result.merge(related_resolved)

    return result


def _collect_includes(includes: List[str], scope_dir: str) -> List[str]:
    """Expand include paths to concrete file list."""
    files = []
    seen: Set[str] = set()

    for pattern in includes:
        # Resolve relative to scope directory
        full_path = os.path.normpath(os.path.join(scope_dir, pattern))

        if pattern.endswith("/"):
            # Directory: recursive walk
            _walk_directory(full_path.rstrip("/"), files, seen)
        elif any(c in pattern for c in "*?["):
            # Glob pattern
            _glob_pattern(pattern, scope_dir, files, seen)
        elif os.path.isfile(full_path):
            # Exact file
            if full_path not in seen:
                files.append(full_path)
                seen.add(full_path)
        elif os.path.isdir(full_path):
            # Directory without trailing slash — still treat as recursive
            _walk_directory(full_path, files, seen)

    return files


def _walk_directory(dir_path: str, files: List[str], seen: Set[str]) -> None:
    """Recursively collect all files in a directory."""
    skip_dirs = SKIP_DIRS

    if not os.path.isdir(dir_path):
        return

    # Check cache: reuse previous walk if directory mtime is unchanged
    try:
        current_mtime = os.path.getmtime(dir_path)
    except OSError:
        current_mtime = 0.0

    cached = _dir_cache.get(dir_path)
    if cached is not None and cached[0] == current_mtime:
        for full in cached[1]:
            if full not in seen:
                files.append(full)
                seen.add(full)
        return

    # Walk and cache
    walked: List[str] = []
    for dirpath, dirnames, filenames in os.walk(dir_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            walked.append(full)
            if full not in seen:
                files.append(full)
                seen.add(full)

    _dir_cache[dir_path] = (current_mtime, walked)


def _glob_pattern(pattern: str, scope_dir: str, files: List[str], seen: Set[str]) -> None:
    """Expand a glob pattern relative to scope directory."""
    base = Path(scope_dir)
    for match in sorted(base.glob(pattern)):
        if match.is_file():
            full = str(match)
            if full not in seen:
                files.append(full)
                seen.add(full)


def _apply_excludes(files: List[str], excludes: List[str], scope_dir: str) -> List[str]:
    """Filter out files matching exclude patterns."""
    if not excludes:
        return files

    result = []
    for f in files:
        rel_path = os.path.relpath(f, scope_dir).replace(os.sep, "/")
        excluded = False

        for pattern in excludes:
            # Check against relative path
            if fnmatch.fnmatch(rel_path, pattern):
                excluded = True
                break
            # Check against filename only
            if fnmatch.fnmatch(os.path.basename(f), pattern):
                excluded = True
                break
            # Check if file is under an excluded directory
            if pattern.endswith("/"):
                dir_prefix = pattern.rstrip("/")
                if rel_path.startswith(dir_prefix + "/") or rel_path.startswith(dir_prefix + os.sep):
                    excluded = True
                    break
            # Also match with ** prefix for nested patterns
            if "/" in pattern and fnmatch.fnmatch(rel_path, "**/" + pattern):
                excluded = True
                break

        if not excluded:
            result.append(f)

    return result


def _load_related(
    related_path: str, scope_dir: str, root: str
) -> Optional[ScopeConfig]:
    """Load a related scope file."""
    from .discovery import find_resolution_scope
    from .paths import strip_inline_comment
    related_path = strip_inline_comment(related_path)

    # Try relative to scope directory first
    candidate = os.path.normpath(os.path.join(scope_dir, related_path))
    config = find_resolution_scope(candidate, root=root)
    if config is not None:
        return config

    # Try relative to root
    candidate = os.path.normpath(os.path.join(root, related_path))
    config = find_resolution_scope(candidate, root=root)
    if config is not None:
        return config

    return None
