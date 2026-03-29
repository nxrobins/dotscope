"""Voice injection into resolve responses and canonical snippet extraction."""

import ast
import os
from typing import Dict, List, Optional

from ..models.intent import CanonicalExample
from ..textio import read_repo_text


def build_voice_response(
    voice_config: dict,
    root: str,
    scope_files: List[str],
    conventions: Optional[list] = None,
) -> dict:
    """Build the voice field for a resolve_scope response.

    Returns a dict with mode, global rules, and optional convention voice.
    """
    result = {
        "mode": voice_config.get("mode", "adaptive"),
        "global": _serialize_global(voice_config),
    }

    # Convention-specific voice (if any file matches a convention with voice config)
    if conventions:
        for conv in conventions:
            conv_voice = getattr(conv, "voice", None)
            if not conv_voice:
                # Check if convention dict has voice key
                if isinstance(conv, dict):
                    conv_voice = conv.get("voice")
                else:
                    continue
            if not conv_voice:
                continue

            canonical = conv_voice.get("canonical_example") if isinstance(conv_voice, dict) else None
            if canonical:
                snippet = extract_canonical_snippet(canonical, root)
                if snippet:
                    result["convention"] = {
                        "name": getattr(conv, "name", "") if not isinstance(conv, dict) else conv.get("name", ""),
                        "style_notes": conv_voice.get("style_notes", "") if isinstance(conv_voice, dict) else "",
                        "canonical_snippet": snippet,
                    }
                    break

    return result


def _serialize_global(voice_config: dict) -> str:
    """Serialize voice rules as compact prose for the agent."""
    rules = voice_config.get("rules", {})
    if not rules:
        return ""

    parts = []
    for key in ("typing", "docstrings", "error_handling", "structure", "density", "comments", "imports"):
        val = rules.get(key)
        if val:
            parts.append(val.strip())

    return " ".join(parts)


def extract_canonical_snippet(
    file_path: str,
    repo_root: str,
    max_lines: int = 40,
) -> Optional[str]:
    """Extract the first class or function as a canonical snippet.

    Uses AST node locations to skip imports and module docstrings.
    """
    full_path = os.path.join(repo_root, file_path) if not os.path.isabs(file_path) else file_path
    if not os.path.isfile(full_path):
        return None

    try:
        source = read_repo_text(full_path).text
        tree = ast.parse(source)
    except (SyntaxError, IOError, OSError):
        return None

    # Find the first class or function definition
    target = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            target = node
            break
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            target = node
            break

    if not target:
        return None

    # Extract source segment
    snippet = ast.get_source_segment(source, target)
    if not snippet:
        # Fallback: extract by line numbers
        lines = source.splitlines()
        start = target.lineno - 1
        end_line = getattr(target, "end_lineno", None) or (start + max_lines)
        end = min(end_line, start + max_lines)
        snippet = "\n".join(lines[start:end])

    # Truncate if too long
    snippet_lines = snippet.splitlines()
    if len(snippet_lines) > max_lines:
        snippet = "\n".join(snippet_lines[:max_lines]) + "\n    ..."

    return snippet


def select_canonical(
    convention: object,
    nodes: list,
    history: Optional[dict],
    repo_root: str,
) -> Optional[CanonicalExample]:
    """Pick the most representative file and extract its first class/function.

    Selection: zero violations, most recently maintained, median length.
    """
    compliant = [n for n in nodes if not getattr(n, "violations", None)]
    if not compliant:
        return None

    # Sort by recency if history available
    if history and history.get("file_histories"):
        compliant.sort(
            key=lambda n: history["file_histories"]
                .get(getattr(n, "file_path", ""), {})
                .get("last_modified", ""),
            reverse=True,
        )

    # Pick median length
    lengths = []
    for n in compliant[:10]:
        fp = getattr(n, "file_path", "")
        full = os.path.join(repo_root, fp)
        try:
            length = len(read_repo_text(full).text.splitlines())
        except (IOError, OSError):
            length = 0
        lengths.append((n, length))

    lengths.sort(key=lambda x: x[1])
    best = lengths[len(lengths) // 2][0]
    best_path = getattr(best, "file_path", "")

    snippet = extract_canonical_snippet(best_path, repo_root)

    return CanonicalExample(
        file_path=best_path,
        snippet=snippet,
    )
