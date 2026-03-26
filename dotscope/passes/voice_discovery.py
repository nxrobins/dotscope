"""Voice discovery: scan codebase for coding style patterns.

Analyzes type hint adoption, docstring style, error handling,
structural preferences, and comprehension density. On new codebases,
returns prescriptive defaults. On existing codebases, codifies
what's already there.
"""

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..models.intent import DiscoveredVoice


@dataclass
class VoiceStats:
    """Raw measurements from a codebase scan."""
    total_functions: int = 0
    typed_functions: int = 0
    total_docstrings: int = 0
    docstring_styles: Dict[str, int] = field(default_factory=lambda: {
        "google": 0, "sphinx": 0, "numpy": 0, "other": 0,
    })
    total_excepts: int = 0
    bare_excepts: int = 0
    total_return_functions: int = 0
    early_return_functions: int = 0
    comprehensions: int = 0
    for_loops: int = 0
    files_analyzed: int = 0


def detect_codebase_maturity(
    ast_data: Dict[str, object],
    history: Optional[object] = None,
    override: Optional[str] = None,
) -> str:
    """Determine if this is a new or existing codebase.

    Returns "new" or "existing".

    Args:
        override: "prescriptive" forces "new", "adaptive" forces "existing".
    """
    if override == "prescriptive":
        return "new"
    if override == "adaptive":
        return "existing"

    file_count = len(ast_data)
    commit_count = getattr(history, "commits_analyzed", 0) if history else 0

    if file_count < 10 or commit_count < 20:
        return "new"
    return "existing"


def discover_voice(
    ast_data: Dict[str, object],
    repo_root: str,
) -> DiscoveredVoice:
    """Analyze the codebase to determine its existing voice.

    Scans structural patterns across all files to determine type hint
    adoption, docstring style, error handling, structural preferences,
    and comprehension density.
    """
    stats = VoiceStats()

    for path, analysis in ast_data.items():
        full_path = os.path.join(repo_root, path)
        if not os.path.isfile(full_path):
            continue
        if not path.endswith(".py"):
            continue

        # Count typed functions from existing FileAnalysis
        for fn in getattr(analysis, "functions", []):
            stats.total_functions += 1
            if fn.return_type or any(
                p for p in fn.params if ":" in str(p)
            ):
                stats.typed_functions += 1

        # Re-parse for deeper analysis
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
        except (SyntaxError, IOError, UnicodeDecodeError):
            continue

        stats.files_analyzed += 1

        # Docstrings
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    stats.total_docstrings += 1
                    style = _detect_docstring_style(docstring)
                    stats.docstring_styles[style] += 1

        # Exception handling
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                stats.total_excepts += 1
                if node.type is None:
                    stats.bare_excepts += 1

        # Early returns
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stats.total_return_functions += 1
                if _has_early_return(node):
                    stats.early_return_functions += 1

        # Comprehensions vs loops
        for node in ast.walk(tree):
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                stats.comprehensions += 1
            elif isinstance(node, ast.For):
                stats.for_loops += 1

    return _synthesize_voice(stats)


def _detect_docstring_style(docstring: str) -> str:
    """Classify a docstring as Google, Sphinx, Numpy, or other."""
    if re.search(r"^\s*(Args|Returns|Raises|Yields|Examples):", docstring, re.MULTILINE):
        return "google"
    if re.search(r"^\s*:(param|type|returns?|rtype|raises)\s*", docstring, re.MULTILINE):
        return "sphinx"
    if re.search(r"^\s*(Parameters|Returns|Raises)\s*\n\s*-{3,}", docstring, re.MULTILINE):
        return "numpy"
    return "other"


def _has_early_return(node: ast.FunctionDef) -> bool:
    """Check if a function has a return before its final statement."""
    body = node.body
    if len(body) <= 1:
        return False
    for stmt in body[:-1]:
        if isinstance(stmt, ast.Return):
            return True
        if isinstance(stmt, ast.If):
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Return):
                    return True
    return False


def _synthesize_voice(stats: VoiceStats) -> DiscoveredVoice:
    """Convert raw stats into a voice description."""
    rules = {}

    # Type hints
    hint_rate = stats.typed_functions / max(stats.total_functions, 1)
    if hint_rate > 0.8:
        rules["typing"] = "Strict type hints on all function signatures."
    elif hint_rate > 0.4:
        rules["typing"] = "Type hints used on most functions. Follow existing patterns."
    else:
        rules["typing"] = "Type hints encouraged on new code but not required."

    # Docstrings
    if stats.total_docstrings > 0:
        dominant = max(stats.docstring_styles, key=stats.docstring_styles.get)
        if dominant == "other":
            rules["docstrings"] = "Minimal docstrings. Add only when behavior is non-obvious."
        else:
            rules["docstrings"] = f"{dominant.title()} style. Match existing docstrings."
    else:
        rules["docstrings"] = "Minimal docstrings. Add only when behavior is non-obvious."

    # Error handling
    bare_rate = stats.bare_excepts / max(stats.total_excepts, 1)
    if bare_rate < 0.1:
        rules["error_handling"] = "No bare excepts. Catch specific exception types."
    elif bare_rate < 0.3:
        rules["error_handling"] = "Avoid bare excepts in new code."
    else:
        rules["error_handling"] = "Match existing error handling patterns."

    # Structure
    early_rate = stats.early_return_functions / max(stats.total_return_functions, 1)
    if early_rate > 0.6:
        rules["structure"] = "Early returns preferred. Guard clauses at the top."
    else:
        rules["structure"] = "Match the pattern of the file being modified."

    # Density
    if stats.comprehensions > stats.for_loops * 0.5 and stats.comprehensions > 3:
        rules["density"] = "Comprehensions preferred where readable."
    else:
        rules["density"] = "Explicit loops. Comprehensions for simple cases only."

    enforce = compute_enforcement({
        "type_hint_rate": round(hint_rate, 2),
        "bare_except_rate": round(bare_rate, 2),
    })

    return DiscoveredVoice(
        mode="adaptive",
        rules=rules,
        stats={
            "type_hint_rate": round(hint_rate, 2),
            "bare_except_rate": round(bare_rate, 2),
            "early_return_rate": round(early_rate, 2),
            "docstring_count": stats.total_docstrings,
            "dominant_docstring_style": max(
                stats.docstring_styles, key=stats.docstring_styles.get,
            ) if stats.total_docstrings else None,
            "files_analyzed": stats.files_analyzed,
        },
        enforce=enforce,
    )


def compute_enforcement(stats: dict) -> dict:
    """Derive enforcement levels from actual codebase state.

    Only enforce what the codebase already does.
    """
    enforce = {}

    bare_rate = stats.get("bare_except_rate", 1.0)
    if bare_rate < 0.10:
        enforce["bare_excepts"] = "hold"
    elif bare_rate < 0.30:
        enforce["bare_excepts"] = "note"
    else:
        enforce["bare_excepts"] = False

    hint_rate = stats.get("type_hint_rate", 0.0)
    if hint_rate > 0.80:
        enforce["missing_type_hints"] = "note"
    else:
        enforce["missing_type_hints"] = False

    return enforce
