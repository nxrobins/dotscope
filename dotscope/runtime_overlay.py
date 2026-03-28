"""Runtime-only scope overlay under .dotscope/runtime_scopes/.

The runtime overlay mirrors the repo scope layout without touching tracked
.scope files. Resolution prefers this layer, but each loaded ScopeConfig keeps
its logical tracked path so freshness accounting stays keyed to repo paths.
"""

import os
import posixpath
import shutil
from typing import Iterable, List, Optional, Tuple

from .models import ScopeConfig, ScopeEntry, ScopesIndex
from .paths import normalize_relative_path, normalize_scope_ref, scope_storage_key


_RUNTIME_SCOPES_DIR = os.path.join(".dotscope", "runtime_scopes")


def runtime_scopes_root(root: str) -> str:
    """Return the runtime overlay root for a repository."""
    return os.path.join(root, _RUNTIME_SCOPES_DIR)


def runtime_index_path(root: str) -> str:
    """Return the runtime overlay index path."""
    return os.path.join(runtime_scopes_root(root), ".scopes")


def logical_scope_path(name_or_path: str, root: Optional[str] = None) -> str:
    """Return a canonical repo-relative scope path like auth/.scope."""
    candidate = name_or_path
    if root and os.path.isabs(candidate):
        try:
            candidate = os.path.relpath(candidate, root)
        except ValueError:
            pass

    if candidate.endswith(".scope"):
        return normalize_scope_ref(candidate)

    normalized = normalize_relative_path(candidate).rstrip("/")
    if not normalized:
        return ".scope"
    return normalize_scope_ref(f"{normalized}/.scope")


def scope_name_from_logical_path(scope_path: str) -> str:
    """Return the scope name/directory from a logical scope path."""
    normalized = logical_scope_path(scope_path)
    directory = posixpath.dirname(normalized)
    return directory or "."


def tracked_scope_path(root: str, scope_path: str) -> str:
    """Return the tracked absolute scope path for a logical scope path."""
    logical = logical_scope_path(scope_path)
    return os.path.join(root, logical.replace("/", os.sep))


def runtime_scope_path(root: str, scope_path: str) -> str:
    """Return the runtime overlay absolute path for a logical scope path."""
    logical = logical_scope_path(scope_path)
    return os.path.join(runtime_scopes_root(root), logical.replace("/", os.sep))


def logical_scope_path_from_runtime(root: str, runtime_path: str) -> str:
    """Convert a runtime overlay path back into a logical scope path."""
    rel = os.path.relpath(runtime_path, runtime_scopes_root(root))
    return normalize_scope_ref(rel)


def runtime_scope_exists(root: str, scope_path: str) -> bool:
    """Return True if a runtime overlay scope exists for the logical scope."""
    return os.path.isfile(runtime_scope_path(root, scope_path))


def load_runtime_index(root: str) -> Optional[ScopesIndex]:
    """Load the runtime overlay index if present."""
    from .parser import parse_scopes_index

    path = runtime_index_path(root)
    if os.path.isfile(path):
        return parse_scopes_index(path)
    return None


def save_runtime_index(root: str, index: ScopesIndex) -> None:
    """Persist the runtime overlay index."""
    from .ingest import _serialize_index

    path = runtime_index_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_serialize_index(index))


def load_effective_index(root: str) -> Optional[ScopesIndex]:
    """Merge tracked and runtime indices, with runtime entries taking precedence."""
    from .discovery import load_index

    tracked = load_index(root)
    runtime = load_runtime_index(root)
    if tracked is None and runtime is None:
        return None

    base = tracked or runtime or ScopesIndex()
    merged = ScopesIndex(
        version=(runtime.version if runtime else base.version),
        scopes=dict(base.scopes),
        defaults=dict(base.defaults),
        total_repo_tokens=base.total_repo_tokens,
    )

    if runtime:
        if runtime.defaults:
            merged.defaults = dict(runtime.defaults)
        if runtime.total_repo_tokens:
            merged.total_repo_tokens = runtime.total_repo_tokens
        merged.scopes.update(runtime.scopes)

    return merged


def iter_runtime_scope_files(root: str) -> List[str]:
    """Return every runtime overlay .scope file."""
    runtime_root = runtime_scopes_root(root)
    if not os.path.isdir(runtime_root):
        return []

    scope_files: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(runtime_root):
        if ".scope" in filenames:
            scope_files.append(os.path.join(dirpath, ".scope"))
    return sorted(scope_files)


def iter_effective_scope_paths(root: str) -> List[str]:
    """Return the union of tracked and runtime logical scope paths."""
    from .discovery import find_all_scopes

    logical_paths = {
        scope_storage_key(scope_path, root=root)
        for scope_path in find_all_scopes(root)
    }
    logical_paths.update(
        logical_scope_path_from_runtime(root, scope_path)
        for scope_path in iter_runtime_scope_files(root)
    )

    index = load_effective_index(root)
    if index:
        logical_paths.update(entry.path for entry in index.scopes.values())

    return sorted(path for path in logical_paths if path)


def load_scope_from_logical_path(
    root: str,
    scope_path: str,
    prefer_runtime: bool = True,
) -> Tuple[Optional[ScopeConfig], Optional[str]]:
    """Load a scope by logical path, optionally preferring the runtime overlay."""
    from .parser import parse_scope_file

    logical = logical_scope_path(scope_path, root=root)
    candidates: List[Tuple[str, str]] = []
    runtime_path = runtime_scope_path(root, logical)
    tracked_path = tracked_scope_path(root, logical)

    if prefer_runtime:
        candidates.extend([
            (runtime_path, "runtime_overlay"),
            (tracked_path, "tracked_snapshot"),
        ])
    else:
        candidates.extend([
            (tracked_path, "tracked_snapshot"),
            (runtime_path, "runtime_overlay"),
        ])

    for source_path, source in candidates:
        if not os.path.isfile(source_path):
            continue
        try:
            config = parse_scope_file(source_path)
        except (ValueError, IOError):
            continue
        config.path = tracked_path
        return config, source

    return None, None


def find_effective_scope_with_source(
    name_or_path: str,
    root: Optional[str] = None,
) -> Tuple[Optional[ScopeConfig], Optional[str]]:
    """Resolve a scope using runtime overlay first, with tracked fallback."""
    from .discovery import find_repo_root
    from .parser import parse_scope_file

    raw = name_or_path.strip()

    if root is None:
        root = find_repo_root()

    if root is None:
        if raw.endswith(".scope") and os.path.isfile(raw):
            config = parse_scope_file(raw)
            return config, "direct"
        return None, None

    # Absolute direct scope file path
    if raw.endswith(".scope") and os.path.isfile(raw):
        logical = logical_scope_path(raw, root=root)
        config, source = load_scope_from_logical_path(root, logical, prefer_runtime=True)
        if config is not None:
            return config, source
        try:
            return parse_scope_file(raw), "direct"
        except (ValueError, IOError):
            return None, None

    # Absolute directory containing a scope
    if os.path.isdir(raw):
        candidate = os.path.join(raw, ".scope")
        if os.path.isfile(candidate):
            logical = logical_scope_path(candidate, root=root)
            return load_scope_from_logical_path(root, logical, prefer_runtime=True)

    index = load_effective_index(root)
    if index and raw in index.scopes:
        return load_scope_from_logical_path(
            root,
            index.scopes[raw].path,
            prefer_runtime=True,
        )

    normalized = normalize_relative_path(raw).rstrip("/")
    if normalized:
        config, source = load_scope_from_logical_path(
            root,
            logical_scope_path(normalized, root=root),
            prefer_runtime=True,
        )
        if config is not None:
            return config, source

        if normalized.endswith(".scope"):
            config, source = load_scope_from_logical_path(
                root,
                normalized,
                prefer_runtime=True,
            )
            if config is not None:
                return config, source

    return None, None


def find_effective_scope(name_or_path: str, root: Optional[str] = None) -> Optional[ScopeConfig]:
    """Resolve a scope using runtime overlay first, with tracked fallback."""
    config, _source = find_effective_scope_with_source(name_or_path, root=root)
    return config


def load_effective_scope_configs(root: str) -> List[Tuple[str, ScopeConfig, str]]:
    """Load every effective scope config once, preferring runtime overlay copies."""
    configs: List[Tuple[str, ScopeConfig, str]] = []
    for logical in iter_effective_scope_paths(root):
        config, source = load_scope_from_logical_path(root, logical, prefer_runtime=True)
        if config is None or source is None:
            continue
        configs.append((logical, config, source))
    return configs


def _build_scope_entry(name: str, logical_path: str, config: ScopeConfig) -> ScopeEntry:
    keywords = list(config.tags)
    for word in config.description.split():
        clean = word.lower().strip("—()-,.")
        if len(clean) > 2 and clean not in keywords:
            keywords.append(clean)
    return ScopeEntry(
        name=name,
        path=logical_path,
        keywords=keywords[:15],
        description=config.description,
    )


def write_runtime_scope(
    root: str,
    config: ScopeConfig,
    scope_name: Optional[str] = None,
) -> str:
    """Write a logical scope config into the runtime overlay and update its index."""
    from .parser import serialize_scope

    logical = scope_storage_key(config.path, root=root) or logical_scope_path(config.path, root=root)
    destination = runtime_scope_path(root, logical)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as f:
        f.write(serialize_scope(config))

    tracked_index = load_effective_index(root)
    runtime_index = load_runtime_index(root)
    index = runtime_index or ScopesIndex(
        version=tracked_index.version if tracked_index else 1,
        scopes={},
        defaults=dict(tracked_index.defaults) if tracked_index else {"max_tokens": 8000, "include_related": False},
        total_repo_tokens=tracked_index.total_repo_tokens if tracked_index else 0,
    )

    name = scope_name or scope_name_from_logical_path(logical)
    index.scopes[name] = _build_scope_entry(name, logical, config)
    save_runtime_index(root, index)
    return destination


def ensure_runtime_scope_copy(root: str, scope_path: str) -> Optional[str]:
    """Ensure the runtime overlay has a copy of a logical/tracked scope."""
    logical = logical_scope_path(scope_path, root=root)
    destination = runtime_scope_path(root, logical)
    if os.path.isfile(destination):
        return destination

    tracked = tracked_scope_path(root, logical)
    if not os.path.isfile(tracked):
        return None

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copyfile(tracked, destination)
    config, _source = load_scope_from_logical_path(root, logical, prefer_runtime=True)
    if config is not None:
        write_runtime_scope(root, config, scope_name=scope_name_from_logical_path(logical))
    return destination


def sync_runtime_overlay(root: str) -> None:
    """Replace the runtime overlay with the current tracked scope snapshot."""
    from .discovery import find_all_scopes

    runtime_root = runtime_scopes_root(root)
    if os.path.isdir(runtime_root):
        shutil.rmtree(runtime_root)
    os.makedirs(runtime_root, exist_ok=True)

    for tracked in find_all_scopes(root):
        logical = scope_storage_key(tracked, root=root)
        if not logical:
            continue
        destination = runtime_scope_path(root, logical)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(tracked, destination)

    tracked_index = os.path.join(root, ".scopes")
    if os.path.isfile(tracked_index):
        shutil.copyfile(tracked_index, runtime_index_path(root))


def replace_runtime_overlay(
    root: str,
    scopes: Iterable[ScopeConfig],
    index: Optional[ScopesIndex] = None,
) -> None:
    """Replace the runtime overlay with generated scope configs."""
    runtime_root = runtime_scopes_root(root)
    if os.path.isdir(runtime_root):
        shutil.rmtree(runtime_root)
    os.makedirs(runtime_root, exist_ok=True)

    entries = {}
    for config in scopes:
        logical = scope_storage_key(config.path, root=root) or logical_scope_path(config.path, root=root)
        destination = runtime_scope_path(root, logical)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        from .parser import serialize_scope

        with open(destination, "w", encoding="utf-8") as f:
            f.write(serialize_scope(config))

        name = scope_name_from_logical_path(logical)
        entries[name] = _build_scope_entry(name, logical, config)

    if index is None:
        effective = load_effective_index(root)
        index = ScopesIndex(
            version=effective.version if effective else 1,
            scopes=entries,
            defaults=dict(effective.defaults) if effective else {"max_tokens": 8000, "include_related": False},
            total_repo_tokens=effective.total_repo_tokens if effective else 0,
        )
    else:
        index = ScopesIndex(
            version=index.version,
            scopes=dict(index.scopes),
            defaults=dict(index.defaults),
            total_repo_tokens=index.total_repo_tokens,
        )

    save_runtime_index(root, index)
