"""Scope health monitoring: staleness, coverage gaps, import drift."""


import os
import re
from typing import Iterable, List, Optional, Set

from .constants import SKIP_DIRS, SOURCE_EXTS
from .models import HealthIssue, HealthReport, ScopeConfig
from .paths import make_relative, normalize, normalize_relative_path
from .textio import iter_repo_text_files, read_repo_text


STALE_TOLERANCE_SECONDS = 2.0


def full_health_report(root: str, use_runtime: bool = True) -> HealthReport:
    """Run all health checks and return a combined report."""
    from .discovery import find_all_scopes, load_resolution_scopes
    from .parser import parse_scope_file
    from .storage.incremental_state import load_incremental_state

    issues: List[HealthIssue] = []
    scoped_dirs: Set[str] = set()
    state = load_incremental_state(root)
    configs: List[ScopeConfig] = []

    if use_runtime:
        for logical_path, config, _source in load_resolution_scopes(root):
            if not config.path:
                config.path = os.path.join(root, logical_path.replace("/", os.sep))
            configs.append(config)
    else:
        for sf in find_all_scopes(root):
            try:
                configs.append(parse_scope_file(sf))
            except (ValueError, IOError) as e:
                issues.append(HealthIssue(
                    scope_path=sf, severity="error",
                    category="parse", message=str(e),
                ))
                continue

    for config in configs:
        scoped_dirs.add(os.path.dirname(config.path))
        issues.extend(check_staleness(config, root, state=state))
        issues.extend(check_broken_paths(config, root))
        issues.extend(check_import_drift(config, root))

    # Coverage check
    all_dirs = _find_source_dirs(root)
    uncovered = all_dirs - scoped_dirs
    coverage_issues = check_coverage(uncovered, root)
    issues.extend(coverage_issues)
    issues.extend(check_encoding(root))

    return HealthReport(
        issues=issues,
        scopes_checked=len(configs),
        directories_total=len(all_dirs),
        directories_covered=len(scoped_dirs),
    )


def check_staleness(
    config: ScopeConfig,
    root: str,
    state=None,
    tolerance_seconds: float = STALE_TOLERANCE_SECONDS,
) -> List[HealthIssue]:
    """Check if files in scope have been modified more recently than the last refresh."""
    issues = []
    refreshed_at = _get_scope_refresh_baseline(root, config, state=state)
    if refreshed_at is None:
        return issues

    stale_files = []

    for filepath in _iter_included_files(config, root):
        fmtime = _get_mtime(filepath)
        if fmtime and fmtime > refreshed_at + tolerance_seconds:
            stale_files.append(make_relative(filepath, root))

    if stale_files:
        count = len(stale_files)
        sample = stale_files[:3]
        msg = f"{count} file(s) modified since scope was last refreshed: {', '.join(sample)}"
        if count > 3:
            msg += f" (+{count - 3} more)"
        issues.append(HealthIssue(
            scope_path=config.path, severity="warning",
            category="staleness", message=msg,
        ))

    return issues


def check_broken_paths(config: ScopeConfig, root: str = "") -> List[HealthIssue]:
    """Check for include/related paths that don't exist."""
    from .paths import path_exists, strip_inline_comment

    issues = []
    scope_dir = config.directory
    base = root or scope_dir

    for inc in config.includes:
        if not path_exists(base, inc):
            issues.append(HealthIssue(
                scope_path=config.path, severity="error",
                category="broken_path", message=f"include not found: {inc}",
            ))

    for rel in config.related:
        clean = strip_inline_comment(rel)
        # Related paths are repo-root-relative; try root first, then scope dir
        if not path_exists(base, clean) and not path_exists(scope_dir, clean):
            issues.append(HealthIssue(
                scope_path=config.path, severity="warning",
                category="broken_path", message=f"related scope not found: {clean}",
            ))

    return issues


def check_import_drift(config: ScopeConfig, root: str = "") -> List[HealthIssue]:
    """Check if imports in scoped files reference modules not in includes."""
    issues = []
    scope_root = root or _infer_scope_root(config)
    if not scope_root:
        return issues

    scope_name = normalize_relative_path(make_relative(config.directory, scope_root)).split("/")[0]
    included_dirs = set()

    for inc in config.includes:
        normalized = normalize_relative_path(inc)
        if normalized.endswith("/"):
            included_dirs.add(normalized.rstrip("/").split("/")[0])
        elif "/" in normalized:
            included_dirs.add(normalized.split("/")[0])

    # Find Python files in includes and check their imports
    drifted = set()
    for f in _iter_included_files(config, scope_root, suffixes=(".py",)):
        try:
            source = read_repo_text(f).text
        except (IOError, OSError):
            continue
        for line in source.splitlines():
            m = re.match(r"from\s+([\w.]+)\s+import", line.strip())
            if m:
                module = m.group(1).split(".")[0]
                candidate = os.path.join(scope_root, module)
                if (
                    os.path.isdir(candidate)
                    and module not in included_dirs
                    and module != scope_name
                    and module not in SKIP_DIRS
                ):
                    drifted.add(module)

    if drifted:
        msg = f"imports reference modules not in includes: {', '.join(sorted(drifted))}"
        issues.append(HealthIssue(
            scope_path=config.path, severity="info",
            category="drift", message=msg,
        ))

    return issues


def check_coverage(uncovered: Set[str], root: str) -> List[HealthIssue]:
    """Report directories that have source files but no .scope."""
    issues = []
    for d in sorted(uncovered):
        rel = os.path.relpath(d, root)
        # Only report if directory has source files
        has_source = any(
            fn.endswith((".py", ".js", ".ts", ".go", ".rs", ".rb", ".java"))
            for fn in os.listdir(d)
            if os.path.isfile(os.path.join(d, fn))
        )
        if has_source:
            issues.append(HealthIssue(
                scope_path="", severity="info",
                category="coverage", message=f"no .scope file: {rel}/",
            ))

    return issues


def check_encoding(root: str) -> List[HealthIssue]:
    """Report repo-authored text files that required lossy decode fallback."""
    issues = []
    for path in iter_repo_text_files(root):
        try:
            decoded = read_repo_text(path)
        except OSError:
            continue
        if decoded.used_replacement:
            issues.append(HealthIssue(
                scope_path=path,
                severity="warning",
                category="encoding",
                message="decoded with replacement characters; file is not valid UTF-8",
            ))
    return issues


def _find_source_dirs(root: str) -> Set[str]:
    """Find all directories under root that contain source files."""
    source_exts = SOURCE_EXTS
    dirs = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        if any(os.path.splitext(f)[1] in source_exts for f in filenames):
            dirs.add(dirpath)

    return dirs


def _get_mtime(path: str) -> Optional[float]:
    """Get file modification time, None if not accessible."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _infer_scope_root(config: ScopeConfig) -> Optional[str]:
    """Infer the repository root for a scope when one is not passed in."""
    from .discovery import find_repo_root

    return find_repo_root(config.directory) or os.path.dirname(config.directory)


def _get_scope_refresh_baseline(root: str, config: ScopeConfig, state=None) -> Optional[float]:
    """Return the baseline timestamp for freshness comparisons."""
    from .storage.incremental_state import get_scope_refresh_epoch

    refreshed_at = get_scope_refresh_epoch(root, config.path, state=state)
    if refreshed_at is not None:
        return refreshed_at
    return _get_mtime(config.path)


def _iter_included_files(
    config: ScopeConfig,
    root: str,
    suffixes: Optional[Iterable[str]] = None,
) -> Iterable[str]:
    """Yield concrete files covered by scope includes."""
    allowed_suffixes = tuple(suffixes) if suffixes else None

    for include in config.includes:
        full = normalize(root, include)
        if include.endswith("/") or os.path.isdir(full.rstrip("/\\")):
            dir_path = full.rstrip("/\\")
            if not os.path.isdir(dir_path):
                continue
            for dirpath, _, filenames in os.walk(dir_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if allowed_suffixes and not filepath.endswith(allowed_suffixes):
                        continue
                    yield filepath
        elif os.path.isfile(full):
            if allowed_suffixes and not full.endswith(allowed_suffixes):
                continue
            yield full
