"""Output formatting: plain, json, cursor."""

import json
import os
from typing import Optional

from ..models import ResolvedScope
from ..paths import make_relative


def format_resolved(
    resolved: ResolvedScope,
    fmt: str = "plain",
    root: Optional[str] = None,
    show_tokens: bool = False,
) -> str:
    """Format a resolved scope for output.

    Formats:
        plain  — One file path per line, with comments for context/excludes
        json   — Full JSON object
        cursor — .cursorrules-style: context + file list for pasting into agent prompts
    """
    if fmt == "json":
        return _format_json(resolved, root)
    elif fmt == "cursor":
        return _format_cursor(resolved, root)
    else:
        return _format_plain(resolved, root, show_tokens)


def _format_plain(resolved: ResolvedScope, root: Optional[str], show_tokens: bool) -> str:
    """Plain format: one file per line."""
    lines = []

    for f in resolved.files:
        path = make_relative(f, root)
        if show_tokens:
            from ..engine.tokens import estimate_file_tokens
            tokens = estimate_file_tokens(f)
            lines.append(f"{path}  # {tokens} tokens")
        else:
            lines.append(path)

    if resolved.excluded_files:
        lines.append("")
        lines.append(f"# Excluded: {len(resolved.excluded_files)} files")

    if resolved.truncated:
        lines.append(f"# Truncated to fit token budget ({resolved.token_estimate} tokens)")

    if resolved.context:
        lines.append("")
        lines.append(f"# Context: {len(resolved.context)} chars, from {len(resolved.scope_chain)} scope(s)")

    return "\n".join(lines)


def _format_json(resolved: ResolvedScope, root: Optional[str]) -> str:
    """JSON format: full object with all compiled retrieval fields."""
    data = {
        "files": [make_relative(f, root) for f in resolved.files],
        "context": resolved.context,
        "token_estimate": resolved.token_estimate,
        "scope_chain": [make_relative(s, root) for s in resolved.scope_chain],
        "truncated": resolved.truncated,
        "file_count": len(resolved.files),
    }
    if resolved.excluded_files:
        data["excluded_count"] = len(resolved.excluded_files)

    # Compiled retrieval fields (populated by codebase_search)
    if resolved.flattened_abstractions:
        data["flattened_abstractions"] = resolved.flattened_abstractions
    if resolved.constraints:
        data["constraints"] = resolved.constraints
    if resolved.routing:
        data["routing"] = resolved.routing
    if resolved.action_hints:
        data["action_hints"] = resolved.action_hints
    if resolved.retrieval_metadata:
        data["retrieval_metadata"] = resolved.retrieval_metadata

    return json.dumps(data, indent=2)


def _format_cursor(resolved: ResolvedScope, root: Optional[str]) -> str:
    """Cursor-style format for pasting into agent prompts or .cursorrules."""
    parts = []

    if resolved.context:
        parts.append("# Scope Context")
        parts.append("")
        parts.append(resolved.context)
        parts.append("")

    if resolved.files:
        parts.append("# Relevant Files")
        parts.append("")
        for f in resolved.files:
            parts.append(f"- {make_relative(f, root)}")

    if resolved.truncated:
        parts.append("")
        parts.append(f"# Note: file list truncated to {resolved.token_estimate} tokens")

    return "\n".join(parts)


def format_stats(
    scope_stats: list,
    total_files: int,
    total_tokens: int,
) -> str:
    """Format the stats report."""
    lines = [
        f"Repository: {total_files} files, ~{total_tokens:,} tokens",
        "",
        f"{'Scope':<20} {'Files':>6} {'Tokens':>8} {'Savings':>8}",
    ]

    for name, file_count, token_count in scope_stats:
        if total_tokens > 0:
            savings = (1 - token_count / total_tokens) * 100
            lines.append(f"{name:<20} {file_count:>6} {token_count:>8,} {savings:>7.1f}%")
        else:
            lines.append(f"{name:<20} {file_count:>6} {token_count:>8,}     N/A")

    if scope_stats and total_tokens > 0:
        avg_savings = sum(
            (1 - tc / total_tokens) * 100 for _, _, tc in scope_stats
        ) / len(scope_stats)
        lines.append("")
        lines.append(f"Average context reduction: {avg_savings:.1f}%")

        avg_tokens = sum(tc for _, _, tc in scope_stats) / len(scope_stats)
        cost_per_call = (total_tokens - avg_tokens) / 1_000_000 * 3
        lines.append(f"Estimated cost savings at $3/M tokens: ${cost_per_call:.2f} per agent call")

    return "\n".join(lines)


def format_tree(scopes: list, root: str) -> str:
    """Format a visual tree of scopes and relationships."""
    if not scopes:
        return "No .scope files found."

    lines = [os.path.basename(root) + "/"]

    for i, (scope_path, config) in enumerate(scopes):
        is_last = i == len(scopes) - 1
        prefix = "└── " if is_last else "├── "
        rel = os.path.relpath(scope_path, root)
        desc = config.description if config else "?"

        lines.append(f"{prefix}{rel}")
        lines.append(f"{'    ' if is_last else '│   '}  {desc}")

        if config and config.related:
            for j, related in enumerate(config.related):
                r_is_last = j == len(config.related) - 1
                r_prefix = "    └─→ " if r_is_last else "    ├─→ "
                if not is_last:
                    r_prefix = "│   " + r_prefix[4:]
                lines.append(f"{r_prefix}{related}")

    return "\n".join(lines)


