"""Spatial Concierge: AST-safe file move with automatic import rewriting.

When a co-location violation is detected, this module generates a complete
patch that moves the file and rewrites every dependent import statement.
The agent can apply the patch directly — no manual fixup needed.
"""

import ast
import difflib
import os
from typing import Dict, List, Optional

from ..models import DependencyGraph, ProposedFix


def generate_spatial_autofix(
    old_path: str,
    new_path: str,
    graph: DependencyGraph,
    repo_root: str,
) -> ProposedFix:
    """Generate a safe patch to move a file and rewrite all dependent imports.

    Args:
        old_path: Current relative path (e.g. ``src/utils/tax_math.py``).
        new_path: Target relative path (e.g. ``domains/billing/tax_math.py``).
        graph: Dependency graph with import edges.
        repo_root: Repository root for reading source files.

    Returns:
        ProposedFix with shell commands and a unified diff covering all
        import rewrites.
    """
    old_module = _path_to_module(old_path)
    new_module = _path_to_module(new_path)

    # Collect importers from the graph
    node = graph.files.get(old_path)
    importers = list(node.imported_by) if node else []

    diffs: List[str] = []
    rewritten_files: List[str] = []

    for importer_path in importers:
        full_importer = os.path.join(repo_root, importer_path)
        if not os.path.isfile(full_importer):
            continue

        try:
            source = _read_source(full_importer)
        except (IOError, OSError):
            continue

        new_source = _rewrite_imports(source, old_module, new_module)
        if new_source == source:
            continue

        diff = _generate_unified_diff(source, new_source, importer_path)
        if diff:
            diffs.append(diff)
            rewritten_files.append(importer_path)

    # Build the combined diff
    move_header = f"# git mv {old_path} {new_path}\n"
    combined_diff = move_header + "\n".join(diffs)

    return ProposedFix(
        file=old_path,
        reason=f"Move to {new_path} and rewrite {len(rewritten_files)} import(s)",
        predicted_sections=rewritten_files,
        proposed_diff=combined_diff,
        confidence=0.9,
    )


def _path_to_module(path: str) -> str:
    """Convert a file path to a Python module path.

    ``src/api/routes/users.py`` → ``src.api.routes.users``
    ``src/api/__init__.py`` → ``src.api``
    """
    # Strip .py extension
    if path.endswith(".py"):
        path = path[:-3]
    # Handle __init__
    if path.endswith("/__init__") or path.endswith(os.sep + "__init__"):
        path = os.path.dirname(path)
    return path.replace("/", ".").replace(os.sep, ".")


def _rewrite_imports(source: str, old_module: str, new_module: str) -> str:
    """Rewrite import statements in source code using AST transformation.

    Only rewrites exact module matches or submodule prefixes to avoid
    false positives (e.g. ``tax_math_extended`` is NOT rewritten when
    moving ``tax_math``).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source  # Can't parse — return unchanged

    rewriter = _ImportRewriter(old_module, new_module)
    new_tree = rewriter.visit(tree)

    if not rewriter.changed:
        return source

    ast.fix_missing_locations(new_tree)
    try:
        return ast.unparse(new_tree)
    except Exception:
        return source  # Unparse failed — return unchanged


class _ImportRewriter(ast.NodeTransformer):
    """AST transformer that rewrites matching import statements."""

    def __init__(self, old_module: str, new_module: str):
        self.old_module = old_module
        self.new_module = new_module
        self.changed = False

    def _rewrite_module(self, module: str) -> Optional[str]:
        """Rewrite a module path if it matches old_module exactly or as prefix."""
        if module == self.old_module:
            return self.new_module
        if module.startswith(self.old_module + "."):
            return self.new_module + module[len(self.old_module):]
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        if node.module:
            rewritten = self._rewrite_module(node.module)
            if rewritten is not None:
                node.module = rewritten
                self.changed = True
        return node

    def visit_Import(self, node: ast.Import) -> ast.Import:
        for alias in node.names:
            rewritten = self._rewrite_module(alias.name)
            if rewritten is not None:
                alias.name = rewritten
                self.changed = True
        return node


def _read_source(filepath: str) -> str:
    """Read source file with UTF-8 fallback."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _generate_unified_diff(
    original: str, modified: str, filepath: str
) -> str:
    """Generate a unified diff between original and modified source."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    diff_lines = difflib.unified_diff(
        orig_lines, mod_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    )
    return "".join(diff_lines)
