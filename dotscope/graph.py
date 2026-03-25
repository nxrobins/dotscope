"""Dependency graph analysis: parse imports, build graph, detect module boundaries.

Uses import/require/use statements to build a file-level dependency graph,
then applies community detection to find natural scope boundaries.
"""


import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .constants import SKIP_DIRS


@dataclass
class FileNode:
    """A file in the dependency graph."""
    path: str  # Relative to root
    language: str
    imports: List[str] = field(default_factory=list)  # Resolved relative paths
    imported_by: List[str] = field(default_factory=list)
    tokens: int = 0


@dataclass
class ModuleBoundary:
    """A detected module boundary (candidate scope)."""
    directory: str  # Relative to root
    files: List[str] = field(default_factory=list)
    internal_edges: int = 0  # Imports within this module
    external_edges: int = 0  # Imports crossing module boundary
    external_deps: List[str] = field(default_factory=list)  # Other modules this depends on
    depended_on_by: List[str] = field(default_factory=list)  # Modules that depend on this
    cohesion: float = 0.0  # internal_edges / (internal + external), higher = better boundary
    churn: int = 0  # From git history (populated later)
    hotspot_files: List[str] = field(default_factory=list)


@dataclass
class DependencyGraph:
    """Full dependency graph of a codebase."""
    root: str
    files: Dict[str, FileNode] = field(default_factory=dict)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (from, to)
    modules: List[ModuleBoundary] = field(default_factory=list)


def build_graph(root: str) -> DependencyGraph:
    """Build a full dependency graph from a codebase.

    1. Walk all source files
    2. Parse imports from each file
    3. Resolve imports to actual file paths
    4. Detect module boundaries using directory structure + import cohesion
    """
    root = os.path.abspath(root)
    graph = DependencyGraph(root=root)

    # Collect all source files
    source_files = _collect_source_files(root)

    # Parse imports from each file
    for rel_path, language in source_files:
        abs_path = os.path.join(root, rel_path)
        raw_imports = _parse_imports(abs_path, language)
        resolved = _resolve_imports(raw_imports, rel_path, root, language)

        node = FileNode(
            path=rel_path,
            language=language,
            imports=resolved,
        )
        graph.files[rel_path] = node

    # Build edge list and back-references
    for path, node in graph.files.items():
        for imp in node.imports:
            graph.edges.append((path, imp))
            if imp in graph.files:
                graph.files[imp].imported_by.append(path)

    # Detect module boundaries
    graph.modules = _detect_modules(graph)

    return graph


def _collect_source_files(root: str) -> List[Tuple[str, str]]:
    """Walk the tree and collect (relative_path, language) for source files."""
    results = []
    lang_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
        ".rs": "rust", ".rb": "ruby", ".java": "java", ".kt": "kotlin",
    }

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in lang_map:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                results.append((rel, lang_map[ext]))

    return sorted(results)


def _parse_imports(filepath: str, language: str) -> List[str]:
    """Parse import statements from a file. Returns raw import strings."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (IOError, OSError):
        return []

    if language == "python":
        return _parse_python_imports(content)
    elif language in ("javascript", "typescript"):
        return _parse_js_imports(content)
    elif language == "go":
        return _parse_go_imports(content)
    return []


def _parse_python_imports(content: str) -> List[str]:
    """Extract Python import targets."""
    imports = []
    for line in content.splitlines():
        line = line.strip()
        # from foo.bar import baz
        m = re.match(r"from\s+([\w.]+)\s+import", line)
        if m:
            imports.append(m.group(1))
            continue
        # import foo.bar
        m = re.match(r"import\s+([\w.]+)", line)
        if m:
            imports.append(m.group(1))
    return imports


def _parse_js_imports(content: str) -> List[str]:
    """Extract JS/TS import targets."""
    imports = []
    # import ... from '...'  or  require('...')
    for m in re.finditer(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", content):
        target = m.group(1)
        if target.startswith("."):  # Only relative imports
            imports.append(target)
    return imports


def _parse_go_imports(content: str) -> List[str]:
    """Extract Go import targets."""
    imports = []
    in_block = False
    for line in content.splitlines():
        line = line.strip()
        if line == "import (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if in_block:
            m = re.match(r'"([^"]+)"', line)
            if m:
                imports.append(m.group(1))
        elif line.startswith("import "):
            m = re.match(r'import\s+"([^"]+)"', line)
            if m:
                imports.append(m.group(1))
    return imports


def _resolve_imports(
    raw_imports: List[str], source_file: str, root: str, language: str
) -> List[str]:
    """Resolve raw import strings to relative file paths within the project."""
    resolved = []
    source_dir = os.path.dirname(source_file)

    for imp in raw_imports:
        candidates = _import_to_paths(imp, source_dir, root, language)
        for candidate in candidates:
            full = os.path.join(root, candidate)
            if os.path.exists(full):
                resolved.append(candidate)
                break

    return resolved


def _import_to_paths(
    imp: str, source_dir: str, root: str, language: str
) -> List[str]:
    """Convert an import string to candidate file paths."""
    if language == "python":
        # foo.bar.baz -> foo/bar/baz.py, foo/bar/baz/__init__.py
        parts = imp.split(".")
        base = os.path.join(*parts)
        return [
            base + ".py",
            os.path.join(base, "__init__.py"),
        ]
    elif language in ("javascript", "typescript"):
        # Relative: ./foo/bar -> resolve from source directory
        if imp.startswith("."):
            resolved = os.path.normpath(os.path.join(source_dir, imp))
            exts = [".ts", ".tsx", ".js", ".jsx"]
            candidates = [resolved + ext for ext in exts]
            candidates.append(os.path.join(resolved, "index.ts"))
            candidates.append(os.path.join(resolved, "index.js"))
            return candidates
    return []


def _detect_modules(graph: DependencyGraph) -> List[ModuleBoundary]:
    """Detect natural module boundaries from the dependency graph.

    Strategy: Use top-level directories as candidate boundaries,
    then compute cohesion (ratio of internal to external edges).
    Directories with high cohesion are good scope boundaries.
    """
    # Group files by top-level directory
    dir_files: Dict[str, List[str]] = defaultdict(list)
    for rel_path in graph.files:
        parts = Path(rel_path).parts
        if len(parts) > 1:
            top_dir = parts[0]
        else:
            top_dir = "."  # Root-level files
        dir_files[top_dir].append(rel_path)

    modules = []
    for directory, files in sorted(dir_files.items()):
        if directory == ".":
            continue  # Skip root-level files for now

        file_set = set(files)
        internal = 0
        external = 0
        ext_deps: Set[str] = set()
        dep_by: Set[str] = set()

        for f in files:
            node = graph.files.get(f)
            if not node:
                continue

            for imp in node.imports:
                if imp in file_set:
                    internal += 1
                else:
                    external += 1
                    imp_parts = Path(imp).parts
                    if len(imp_parts) > 1:
                        ext_deps.add(imp_parts[0])

            for imp_by in node.imported_by:
                if imp_by not in file_set:
                    imp_parts = Path(imp_by).parts
                    if len(imp_parts) > 1:
                        dep_by.add(imp_parts[0])

        total = internal + external
        cohesion = internal / total if total > 0 else 1.0

        modules.append(ModuleBoundary(
            directory=directory,
            files=files,
            internal_edges=internal,
            external_edges=external,
            external_deps=sorted(ext_deps - {directory}),
            depended_on_by=sorted(dep_by - {directory}),
            cohesion=round(cohesion, 3),
        ))

    # Sort by file count descending (largest modules first)
    modules.sort(key=lambda m: -len(m.files))
    return modules


def format_graph_summary(graph: DependencyGraph) -> str:
    """Format a human-readable summary of the dependency graph."""
    lines = [
        f"Dependency Graph: {len(graph.files)} files, {len(graph.edges)} edges",
        f"Detected {len(graph.modules)} module(s):",
        "",
    ]

    for mod in graph.modules:
        cohesion_bar = "█" * int(mod.cohesion * 10) + "░" * (10 - int(mod.cohesion * 10))
        lines.append(
            f"  {mod.directory}/ — {len(mod.files)} files, "
            f"cohesion: {cohesion_bar} {mod.cohesion:.0%}"
        )
        if mod.external_deps:
            lines.append(f"    depends on: {', '.join(mod.external_deps)}")
        if mod.depended_on_by:
            lines.append(f"    used by: {', '.join(mod.depended_on_by)}")

    return "\n".join(lines)
