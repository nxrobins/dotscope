"""Minimal YAML subset parser for .scope and .scopes files.

Handles the subset needed: scalars, lists, block scalars (|), comments.
No external dependencies.
"""


import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .context import parse_context
from .models import ScopeConfig, ScopeEntry, ScopesIndex
from .paths import normalize_relative_path, normalize_scope_ref


def parse_scope_file(path: str) -> ScopeConfig:
    """Parse a .scope file into a ScopeConfig."""
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    data = _parse_yaml(text)

    description = data.get("description", "")
    if not description:
        raise ValueError(f"Missing required 'description' field in {path}")

    context_raw = data.get("context", "")
    context = parse_context(context_raw) if context_raw else None

    tokens_est = data.get("tokens_estimate")
    if tokens_est is not None:
        tokens_est = int(tokens_est)

    return ScopeConfig(
        path=path,
        description=str(description),
        includes=[normalize_relative_path(p) for p in _as_list(data.get("includes", []))],
        excludes=[normalize_relative_path(p) for p in _as_list(data.get("excludes", []))],
        context=context,
        related=[normalize_scope_ref(p) for p in _as_list(data.get("related", []))],
        owners=_as_list(data.get("owners", [])),
        tags=_as_list(data.get("tags", [])),
        tokens_estimate=tokens_est,
    )


def parse_scopes_index(path: str) -> ScopesIndex:
    """Parse a .scopes index file."""
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    data = _parse_yaml(text)

    version = int(data.get("version", 1))
    defaults = data.get("defaults", {})
    if isinstance(defaults, str):
        defaults = {}

    scopes_raw = data.get("scopes", {})
    scopes = {}
    if isinstance(scopes_raw, dict):
        for name, entry_data in scopes_raw.items():
            if isinstance(entry_data, dict):
                keywords = entry_data.get("keywords", [])
                if isinstance(keywords, str):
                    # Handle inline [a, b, c] syntax
                    keywords = _parse_inline_list(keywords)
                scopes[name] = ScopeEntry(
                    name=name,
                    path=normalize_scope_ref(str(entry_data.get("path", ""))),
                    keywords=keywords,
                    description=entry_data.get("description"),
                )

    total_repo_tokens = int(data.get("total_repo_tokens", 0))
    return ScopesIndex(
        version=version, scopes=scopes, defaults=defaults,
        total_repo_tokens=total_repo_tokens,
    )


def serialize_scope(config: ScopeConfig) -> str:
    """Serialize a ScopeConfig back to .scope YAML format."""
    lines = []

    lines.append(f"description: {config.description}")

    if config.includes:
        lines.append("includes:")
        for inc in config.includes:
            lines.append(f"  - {inc}")

    if config.excludes:
        lines.append("excludes:")
        for exc in config.excludes:
            if any(c in exc for c in "*?["):
                lines.append(f'  - "{exc}"')
            else:
                lines.append(f"  - {exc}")

    if config.context:
        lines.append("context: |")
        for line in config.context_str.splitlines():
            lines.append(f"  {line}")

    if config.related:
        lines.append("related:")
        for rel in config.related:
            lines.append(f"  - {rel}")

    if config.owners:
        lines.append("owners:")
        for owner in config.owners:
            lines.append(f'  - "{owner}"')

    if config.tags:
        lines.append("tags:")
        for tag in config.tags:
            lines.append(f"  - {tag}")

    if config.tokens_estimate is not None:
        lines.append(f"tokens_estimate: {config.tokens_estimate}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Internal YAML subset parser
# ---------------------------------------------------------------------------

def _parse_yaml(text: str) -> Dict[str, Any]:
    """Parse a YAML subset: scalars, lists, block scalars, nested maps (1 level)."""
    result: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = _strip_comment(line)

        # Skip blank / comment-only lines
        if not stripped.strip():
            i += 1
            continue

        indent = _indent_level(line)

        # Only process top-level keys (indent 0)
        if indent > 0:
            i += 1
            continue

        key, value, i = _parse_key_value(lines, i)
        if key is not None:
            result[key] = value

    return result


def _parse_key_value(lines: List[str], i: int) -> Tuple[Optional[str], Any, int]:
    """Parse a key-value pair starting at line i. Returns (key, value, next_i)."""
    line = _strip_comment(lines[i]).strip()

    m = re.match(r'^(["\']?)([^"\':\s][^"\':]*)(\1)\s*:\s*(.*)', line)
    if not m:
        return None, None, i + 1

    key = m.group(2).strip()
    rest = m.group(4).strip()

    i += 1

    # Block scalar: key: |
    if rest == "|":
        value, i = _parse_block_scalar(lines, i)
        return key, value, i

    # Check if next lines are list items or nested map
    if not rest and i < len(lines):
        next_stripped = _strip_comment(lines[i]).strip() if i < len(lines) else ""
        if next_stripped.startswith("- "):
            value, i = _parse_list(lines, i)
            return key, value, i
        elif ":" in next_stripped and not next_stripped.startswith("-"):
            value, i = _parse_nested_map(lines, i)
            return key, value, i

    # Inline value
    if rest:
        # Inline list: [a, b, c]
        if rest.startswith("[") and rest.endswith("]"):
            return key, _parse_inline_list(rest), i

        # Quoted string
        if (rest.startswith('"') and rest.endswith('"')) or (
            rest.startswith("'") and rest.endswith("'")
        ):
            return key, rest[1:-1], i

        # Try numeric
        try:
            if "." in rest:
                return key, float(rest), i
            return key, int(rest), i
        except ValueError:
            pass

        # Boolean
        if rest.lower() in ("true", "yes"):
            return key, True, i
        if rest.lower() in ("false", "no"):
            return key, False, i

        return key, rest, i

    return key, "", i


def _parse_block_scalar(lines: List[str], i: int) -> Tuple[str, int]:
    """Parse a block scalar (| style) starting at line i."""
    block_lines = []
    if i >= len(lines):
        return "", i

    # Determine base indent from first content line
    base_indent = _indent_level(lines[i])
    if base_indent == 0:
        return "", i

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            block_lines.append("")
            i += 1
            continue
        current_indent = _indent_level(line)
        if current_indent < base_indent:
            break
        block_lines.append(line[base_indent:])
        i += 1

    # Strip trailing empty lines
    while block_lines and not block_lines[-1]:
        block_lines.pop()

    return "\n".join(block_lines), i


def _parse_list(lines: List[str], i: int) -> Tuple[List[str], int]:
    """Parse a YAML list starting at line i."""
    items = []
    if i >= len(lines):
        return items, i

    base_indent = _indent_level(lines[i])

    while i < len(lines):
        line = lines[i]
        stripped = _strip_comment(line).strip()

        if not stripped:
            i += 1
            continue

        current_indent = _indent_level(line)
        if current_indent < base_indent:
            break

        if stripped.startswith("- "):
            item = stripped[2:].strip()
            # Strip quotes
            if (item.startswith('"') and item.endswith('"')) or (
                item.startswith("'") and item.endswith("'")
            ):
                item = item[1:-1]
            # Strip inline comments from list items (e.g., "payments/.scope  # shares user model")
            comment_match = re.match(r'^([^#]*?)\s+#\s+.*$', item)
            if comment_match:
                item = comment_match.group(1).strip()
            items.append(item)
        elif current_indent > base_indent:
            pass  # continuation line, skip
        else:
            break

        i += 1

    return items, i


def _parse_nested_map(lines: List[str], i: int) -> Tuple[Dict[str, Any], int]:
    """Parse a one-level nested map."""
    result: Dict[str, Any] = {}
    if i >= len(lines):
        return result, i

    base_indent = _indent_level(lines[i])

    while i < len(lines):
        line = lines[i]
        stripped = _strip_comment(line).strip()

        if not stripped:
            i += 1
            continue

        current_indent = _indent_level(line)
        if current_indent < base_indent:
            break

        if current_indent == base_indent:
            # This is a nested key
            key, value, i = _parse_key_value(lines, i)
            if key is not None:
                result[key] = value
        else:
            i += 1

    return result, i


def _parse_inline_list(text: str) -> List[str]:
    """Parse [a, b, c] into a list. Handles quoted values containing commas."""
    inner = text.strip()
    if inner.startswith("["):
        inner = inner[1:]
    if inner.endswith("]"):
        inner = inner[:-1]

    # State-machine split: only split on commas outside quotes
    items = []
    current: List[str] = []
    in_quote = None

    for ch in inner:
        if ch in ('"', "'"):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
            else:
                current.append(ch)
            continue
        if ch == "," and in_quote is None:
            val = "".join(current).strip()
            if val:
                items.append(val)
            current = []
            continue
        current.append(ch)

    val = "".join(current).strip()
    if val:
        items.append(val)
    return items


def _strip_comment(line: str) -> str:
    """Strip trailing # comments, respecting quotes."""
    in_quote = None
    for idx, ch in enumerate(line):
        if ch in ('"', "'"):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
        elif ch == "#" and in_quote is None:
            # Only strip if preceded by whitespace or at start
            if idx == 0 or line[idx - 1] in (" ", "\t"):
                return line[:idx]
    return line


def _indent_level(line: str) -> int:
    """Count leading spaces."""
    return len(line) - len(line.lstrip(" "))


def _as_list(val: Any) -> List[str]:
    """Ensure a value is a list of strings."""
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str) and val:
        return [val]
    return []
