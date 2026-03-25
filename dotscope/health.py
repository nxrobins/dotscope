"""Scope health monitoring: staleness, coverage gaps, import drift."""


import os
import re
from typing import List, Optional, Set

from .constants import SKIP_DIRS, SOURCE_EXTS
from .models import HealthIssue, HealthReport, ScopeConfig


def full_health_report(root: str) -> HealthReport:
    """Run all health checks and return a combined report."""
    from .discovery import find_all_scopes
    from .parser import parse_scope_file

    scope_files = find_all_scopes(root)
    issues: List[HealthIssue] = []
    scoped_dirs: Set[str] = set()

    for sf in scope_files:
        try:
            config = parse_scope_file(sf)
        except (ValueError, IOError) as e:
            issues.append(HealthIssue(
                scope_path=sf, severity="error",
                category="parse", message=str(e),
            ))
            continue

        scoped_dirs.add(os.path.dirname(sf))

        issues.extend(check_staleness(config, root))
        issues.extend(check_broken_paths(config, root))
        issues.extend(check_import_drift(config))

    # Coverage check
    all_dirs = _find_source_dirs(root)
    uncovered = all_dirs - scoped_dirs
    coverage_issues = check_coverage(uncovered, root)
    issues.extend(coverage_issues)

    return HealthReport(
        issues=issues,
        scopes_checked=len(scope_files),
        directories_total=len(all_dirs),
        directories_covered=len(scoped_dirs),
    )


def check_staleness(config: ScopeConfig, root: str) -> List[HealthIssue]:
    """Check if files in scope have been modified more recently than the .scope file."""
    issues = []
    scope_mtime = _get_mtime(config.path)
    if scope_mtime is None:
        return issues

    stale_files = []

    for inc in config.includes:
        full = os.path.normpath(os.path.join(root, inc))
        if inc.endswith("/") or os.path.isdir(full.rstrip("/")):
            dir_path = full.rstrip("/")
            if os.path.isdir(dir_path):
                for dirpath, _, filenames in os.walk(dir_path):
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        fmtime = _get_mtime(fp)
                        if fmtime and fmtime > scope_mtime:
                            stale_files.append(os.path.relpath(fp, root))
        elif os.path.isfile(full):
            fmtime = _get_mtime(full)
            if fmtime and fmtime > scope_mtime:
                stale_files.append(os.path.relpath(full, root))

    if stale_files:
        count = len(stale_files)
        sample = stale_files[:3]
        msg = f"{count} file(s) modified since .scope was last updated: {', '.join(sample)}"
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


def check_import_drift(config: ScopeConfig) -> List[HealthIssue]:
    """Check if imports in scoped files reference modules not in includes."""
    issues = []
    scope_dir = config.directory
    included_dirs = set()

    for inc in config.includes:
        full = os.path.normpath(os.path.join(scope_dir, inc))
        if inc.endswith("/") or os.path.isdir(full.rstrip("/")):
            included_dirs.add(os.path.basename(full.rstrip("/")))
        else:
            included_dirs.add(os.path.dirname(inc).split("/")[0] if "/" in inc else "")

    # Find Python files in includes and check their imports
    drifted = set()
    parent = os.path.dirname(scope_dir)

    for inc in config.includes:
        full = os.path.normpath(os.path.join(scope_dir, inc))
        files = []
        if os.path.isdir(full.rstrip("/")):
            for dp, _, fns in os.walk(full.rstrip("/")):
                for fn in fns:
                    if fn.endswith(".py"):
                        files.append(os.path.join(dp, fn))
        elif full.endswith(".py") and os.path.isfile(full):
            files.append(full)

        for f in files:
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        m = re.match(r"from\s+([\w.]+)\s+import", line.strip())
                        if m:
                            module = m.group(1).split(".")[0]
                            candidate = os.path.join(parent, module)
                            if (
                                os.path.isdir(candidate)
                                and module not in included_dirs
                                and candidate != scope_dir
                                and module not in SKIP_DIRS
                            ):
                                drifted.add(module)
            except (IOError, OSError):
                continue

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
