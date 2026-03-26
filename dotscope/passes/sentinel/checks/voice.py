"""Voice check: bare excepts and missing type hints on new functions."""

import ast
import os
from typing import Dict, List, Optional

from ..models import CheckCategory, CheckResult, Severity


def check_voice(
    modified_files: List[str],
    added_lines: Dict[str, List[str]],
    voice_config: Optional[dict],
    repo_root: str,
) -> List[CheckResult]:
    """Mechanical voice checks. Only fires for rules with enforce != false."""
    if not voice_config:
        return []

    enforce = voice_config.get("enforce", {})
    if not enforce:
        return []

    results = []

    for filepath in modified_files:
        if not filepath.endswith(".py"):
            continue

        full_path = os.path.join(repo_root, filepath)
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
        except (SyntaxError, IOError, UnicodeDecodeError):
            continue

        # Bare excepts
        bare_level = enforce.get("bare_excepts")
        if bare_level and bare_level is not False:
            severity = Severity.HOLD if bare_level == "hold" else Severity.NOTE
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    results.append(CheckResult(
                        passed=False,
                        category=CheckCategory.VOICE,
                        severity=severity,
                        message=f"Bare except in {filepath}:{node.lineno}",
                        detail="Catch a specific exception type.",
                        file=filepath,
                        suggestion="Replace `except:` with `except SpecificError:`",
                    ))

        # Missing type hints (only on new/modified functions)
        hint_level = enforce.get("missing_type_hints")
        if hint_level and hint_level is not False:
            severity = Severity.HOLD if hint_level == "hold" else Severity.NOTE

            # Filter to code-only lines (exclude comments and strings)
            from ..line_filter import strip_comments_and_strings
            code_lines = []
            for line in added_lines.get(filepath, []):
                code = strip_comments_and_strings(line)
                if code.strip():
                    code_lines.append(code)

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                # Check if this function definition appears in code-only added lines
                func_line = f"def {node.name}("
                async_line = f"async def {node.name}("
                is_new = any(
                    func_line in line or async_line in line
                    for line in code_lines
                )
                if not is_new:
                    continue

                # Skip dunder methods and test functions
                if node.name.startswith("__") or node.name.startswith("test_"):
                    continue

                has_hints = bool(node.returns)
                if not has_hints:
                    # Check if any param has annotation (skip self/cls)
                    params = [
                        a for a in node.args.args
                        if a.arg not in ("self", "cls")
                    ]
                    has_hints = any(a.annotation for a in params)

                if not has_hints:
                    results.append(CheckResult(
                        passed=False,
                        category=CheckCategory.VOICE,
                        severity=severity,
                        message=f"Missing type hints: {filepath}:{node.name}()",
                        detail="Add type hints to function signature.",
                        file=filepath,
                        suggestion=f"Add type hints to {node.name}()",
                    ))

    return results
