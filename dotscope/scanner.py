"""Auto-generate .scope from directory analysis.

Scans directory structure, detects language, finds cross-directory imports,
and produces a reasonable starting .scope configuration.
"""


import os
import re
from collections import Counter
from typing import List, Optional, Set, Tuple

from .constants import LANG_MAP, SKIP_DIRS
from .context import parse_context
from .models import ScopeConfig
from .tokens import estimate_file_tokens


# Directories to always exclude
_DEFAULT_EXCLUDES = [
    "__pycache__/",
    "node_modules/",
    ".git/",
    "*.pyc",
    "dist/",
    "build/",
    "*.egg-info/",
    ".tox/",
    ".mypy_cache/",
    ".ruff_cache/",
    "venv/",
    ".venv/",
    "*.min.js",
    "*.generated.*",
]

# Directories that are typically test/fixture/migration content
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}
_FIXTURE_DIRS = {"fixtures", "fixture", "testdata", "test_data", "mocks"}
_MIGRATION_DIRS = {"migrations", "migrate", "alembic"}


def scan_directory(path: str) -> ScopeConfig:
    """Analyze a directory and generate a starter .scope configuration.

    The human then edits the context field — that's the part that can't be automated.
    """
    path = os.path.abspath(path)
    dir_name = os.path.basename(path)

    # Collect file info
    files, lang_counts, total_tokens = _scan_files(path)

    # Detect primary language
    primary_lang = _detect_language(lang_counts)

    includes = [f"{dir_name}/"]

    # Build excludes
    excludes = _build_excludes(path)

    # Detect cross-directory imports
    external_deps = _find_external_deps(path, files, primary_lang)

    # Add external dependencies to includes
    for dep in external_deps:
        if dep not in includes:
            includes.append(dep)

    # Build description
    file_count = len(files)
    description = f"{dir_name} -- {primary_lang or 'mixed'} ({file_count} files)"

    # Build tags
    tags = _infer_tags(path, dir_name, files)

    context = parse_context(
        "# TODO: Add architectural context here.\n"
        "# What invariants does this module maintain?\n"
        "# What gotchas should an agent know about?\n"
        "# What conventions does it follow?"
    )

    return ScopeConfig(
        path=os.path.join(path, ".scope"),
        description=description,
        includes=includes,
        excludes=excludes,
        context=context,
        related=[],
        owners=[],
        tags=tags,
        tokens_estimate=total_tokens,
    )


def _scan_files(path: str) -> Tuple[List[str], Counter, int]:
    """Walk directory, collect files, count languages, estimate tokens."""
    files = []
    lang_counts: Counter = Counter()
    total_tokens = 0

    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            full = os.path.join(dirpath, filename)
            files.append(full)

            ext = os.path.splitext(filename)[1].lower()
            if ext in LANG_MAP:
                lang_counts[LANG_MAP[ext]] += 1

            total_tokens += estimate_file_tokens(full)

    return files, lang_counts, total_tokens


def _detect_language(lang_counts: Counter) -> Optional[str]:
    """Detect the primary language from extension counts."""
    if not lang_counts:
        return None
    return lang_counts.most_common(1)[0][0]


def _build_excludes(path: str) -> List[str]:
    """Build excludes from detected directories."""
    excludes = []
    dir_name = os.path.basename(path)

    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        if not os.path.isdir(full):
            continue

        entry_lower = entry.lower()
        if entry_lower in _TEST_DIRS:
            excludes.append(f"{dir_name}/{entry}/fixtures/")
        if entry_lower in _FIXTURE_DIRS:
            excludes.append(f"{dir_name}/{entry}/")
        if entry_lower in _MIGRATION_DIRS:
            excludes.append(f"{dir_name}/{entry}/")
        if entry in SKIP_DIRS:
            excludes.append(f"{dir_name}/{entry}/")

    # Add common glob excludes
    excludes.extend([
        "*.pyc",
        f"{dir_name}/__pycache__/",
    ])

    return list(dict.fromkeys(excludes))  # dedupe preserving order


def _find_external_deps(
    path: str, files: List[str], lang: Optional[str]
) -> List[str]:
    """Parse imports to find cross-directory dependencies."""
    if lang == "Python":
        return _find_python_imports(path, files)
    elif lang in ("JavaScript", "TypeScript"):
        return _find_js_imports(path, files)
    return []


def _find_python_imports(path: str, files: List[str]) -> List[str]:
    """Find Python imports that reference outside the scanned directory."""
    external: Set[str] = set()
    parent = os.path.dirname(path)

    for f in files:
        if not f.endswith(".py"):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    # from foo.bar import baz
                    m = re.match(r"from\s+([\w.]+)\s+import", line)
                    if m:
                        module = m.group(1).split(".")[0]
                        candidate = os.path.join(parent, module)
                        if os.path.isdir(candidate) and candidate != path:
                            rel = os.path.relpath(candidate, parent)
                            external.add(f"{rel}/")
                        candidate_file = os.path.join(parent, module + ".py")
                        if os.path.isfile(candidate_file) and os.path.dirname(candidate_file) != path:
                            rel = os.path.relpath(candidate_file, parent)
                            external.add(rel)
        except (IOError, OSError):
            continue

    return sorted(external)


def _find_js_imports(path: str, files: List[str]) -> List[str]:
    """Find JS/TS imports that reference outside the scanned directory."""
    external: Set[str] = set()
    parent = os.path.dirname(path)

    for f in files:
        if not any(f.endswith(ext) for ext in (".js", ".ts", ".jsx", ".tsx")):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    # import ... from '../foo/bar'
                    # require('../foo/bar')
                    for m in re.finditer(r"""(?:from|require\()\s*['"](\.\./[^'"]+)['"]""", line):
                        rel_import = m.group(1)
                        abs_import = os.path.normpath(os.path.join(os.path.dirname(f), rel_import))
                        if not abs_import.startswith(path):
                            rel = os.path.relpath(abs_import, parent)
                            if os.path.isdir(abs_import):
                                external.add(f"{rel}/")
                            else:
                                external.add(rel)
        except (IOError, OSError):
            continue

    return sorted(external)


def _infer_tags(path: str, dir_name: str, files: List[str]) -> List[str]:
    """Infer tags from directory name and file contents."""
    tags = [dir_name.lower()]

    # Infer from common file/directory names
    name_lower = dir_name.lower()
    tag_hints = {
        "auth": ["authentication", "security"],
        "api": ["rest", "endpoint"],
        "payment": ["billing", "stripe"],
        "user": ["account", "profile"],
        "admin": ["dashboard", "management"],
        "config": ["configuration", "settings"],
        "deploy": ["infrastructure", "ci-cd"],
        "test": ["testing"],
        "model": ["database", "orm"],
    }

    for hint, extra_tags in tag_hints.items():
        if hint in name_lower:
            tags.extend(extra_tags)

    return list(dict.fromkeys(tags))
