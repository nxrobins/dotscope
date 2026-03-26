"""Semantic diff: translate git diff into convention-level structural changes."""

import os
import subprocess
from typing import Dict, List, Optional

from ..models import ConventionNode, ConventionRule, FileAnalysis, SemanticDiffReport
from .convention_parser import parse_conventions


def semantic_diff(
    diff_text: str,
    repo_root: str,
    conventions: List[ConventionRule],
) -> SemanticDiffReport:
    """Translate a git diff into convention-level changes.

    Parses the AST at two points in time:
      1. HEAD commit (using `git show HEAD:<file>` for each modified file)
      2. Working directory (current files on disk)

    Compares the ConventionNode graphs to determine structural changes.
    """
    modified_files = _extract_modified_files(diff_text)
    if not modified_files or not conventions:
        return SemanticDiffReport()

    # Parse conventions at HEAD
    head_ast = {}
    for filepath in modified_files:
        source = _git_show_head(repo_root, filepath)
        if source:
            analysis = _parse_source(source, filepath)
            if analysis:
                head_ast[filepath] = analysis

    nodes_before = parse_conventions(head_ast, conventions)

    # Parse conventions at working directory
    working_ast = {}
    for filepath in modified_files:
        full_path = os.path.join(repo_root, filepath)
        if os.path.exists(full_path):
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
                analysis = _parse_source(source, filepath)
                if analysis:
                    working_ast[filepath] = analysis
            except (IOError, UnicodeDecodeError):
                pass

    nodes_after = parse_conventions(working_ast, conventions)

    before_map = {(n.file_path, n.name): n for n in nodes_before}
    after_map = {(n.file_path, n.name): n for n in nodes_after}

    added = []
    removed = []
    modified = []

    for key, node in after_map.items():
        if key not in before_map:
            added.append(node)
        elif before_map[key].violations != node.violations:
            modified.append((before_map[key], node))

    for key, node in before_map.items():
        if key not in after_map:
            removed.append(node)

    all_upheld = all(not n.violations for n in after_map.values())

    return SemanticDiffReport(
        added=added,
        removed=removed,
        modified=modified,
        all_conventions_upheld=all_upheld,
    )


def format_semantic_diff(report: SemanticDiffReport) -> str:
    """Format a SemanticDiffReport for terminal output."""
    lines = ["Semantic Diff:"]

    for node in report.added:
        lines.append(f"  [ADDED]    {node.name}: {node.file_path}")
    for node in report.removed:
        lines.append(f"  [REMOVED]  {node.name}: {node.file_path}")
    for before, after in report.modified:
        lines.append(f"  [MODIFIED] {after.name}: {after.file_path}")
        for v in after.violations:
            lines.append(f"             ! {v}")
    for dep in report.dependency_changes:
        lines.append(f"  [MODIFIED] Dependency: {dep}")

    lines.append("")
    if report.all_conventions_upheld:
        lines.append("  Conventions: All upheld")
    else:
        violation_count = sum(
            len(n.violations) for n in
            [node for _, node in report.modified] +
            report.added
        )
        lines.append(f"  Conventions: {violation_count} violation(s)")

    if report.counterfactual:
        lines.append("")
        lines.append(f"  {report.counterfactual}")

    return "\n".join(lines)


def _extract_modified_files(diff_text: str) -> List[str]:
    """Extract file paths from unified diff."""
    files = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            if len(parts) > 1:
                filepath = parts[1]
                if filepath not in files:
                    files.append(filepath)
    return files


def _git_show_head(repo_root: str, filepath: str) -> Optional[str]:
    """Get file content at HEAD."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{filepath}"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _parse_source(source: str, filepath: str) -> Optional[FileAnalysis]:
    """Parse source code into FileAnalysis."""
    try:
        from .ast_analyzer import analyze_file
        import tempfile
        # Write to temp file for analyze_file (it reads from disk)
        ext = os.path.splitext(filepath)[1]
        lang = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go"}.get(ext)
        if not lang:
            return None
        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as tf:
            tf.write(source)
            tf.flush()
            try:
                return analyze_file(tf.name, lang)
            finally:
                os.unlink(tf.name)
    except Exception:
        return None
