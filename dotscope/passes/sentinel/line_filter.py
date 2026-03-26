"""Filter added lines to exclude comments and string literals.

Used by checks that apply regex patterns to raw diff lines.
Without filtering, patterns like .delete() would match in comments
and docstrings, causing false positives that block commits.
"""

import re
from typing import List


def strip_comments_and_strings(line: str) -> str:
    """Remove comments and string literals from a Python line.

    Returns the code-only portion. Inline comments are stripped.
    String contents are replaced with empty strings to preserve structure
    but remove matchable content.

    Examples:
        'x.delete()  # remove it' -> 'x.delete()  '
        '# x.delete()' -> ''
        'msg = "call .delete()"' -> 'msg = ""'
        "x.delete()" -> "x.delete()"
    """
    stripped = line.lstrip()

    # Full-line comment
    if stripped.startswith("#"):
        return ""

    # Replace string literals with empty strings (handles both ' and ")
    # This is intentionally simple — not a full parser. Handles:
    #   "text", 'text', f"text", r"text", b"text"
    # Does NOT handle triple-quoted strings spanning multiple lines
    # (those are rare in single added-line diffs).
    result = _replace_strings(line)

    # Strip inline comments (# not inside a string)
    comment_pos = _find_inline_comment(result)
    if comment_pos >= 0:
        result = result[:comment_pos]

    return result


def filter_code_lines(lines: List[str]) -> List[str]:
    """Filter a list of added lines to only code content.

    Removes full-line comments and strips string/comment content
    from code lines. Returns lines that still have matchable code.
    """
    filtered = []
    for line in lines:
        code = strip_comments_and_strings(line)
        if code.strip():
            filtered.append(code)
    return filtered


def _replace_strings(line: str) -> str:
    """Replace string literal contents with empty strings."""
    # Match f-strings, r-strings, b-strings, and plain strings
    # Pattern: optional prefix + quote + non-greedy content + closing quote
    result = re.sub(r'''(?:[fFrRbBuU]?)(""".*?"""|'''  r"""'''.*?'''|"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*')""", '""', line)
    return result


def _find_inline_comment(line: str) -> int:
    """Find position of inline # comment (not inside a string).

    Returns -1 if no inline comment found.
    """
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            i += 2  # Skip escaped character
            continue
        if c == '"' and not in_single:
            in_double = not in_double
        elif c == "'" and not in_double:
            in_single = not in_single
        elif c == "#" and not in_single and not in_double:
            return i
        i += 1
    return -1
