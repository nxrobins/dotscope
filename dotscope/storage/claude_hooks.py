"""Claude Code hook installation for automatic pre-commit routing verification.

Writes a PreToolUse hook that intercepts git commit commands and runs
dotscope check. GUARDs block the commit (exit 2). NUDGEs and NOTEs pass through.
"""

import json
import os
import stat


_HOOK_SCRIPT = """\
#!/bin/bash
# dotscope pre-commit enforcement for Claude Code
#
# Intercepts git commit commands and runs dotscope check on staged changes.
# Exit 2 blocks the commit and feeds the error back to the agent.
# Non-commit Bash commands pass through untouched.

set -e

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only intercept git commit commands
case "$COMMAND" in
    git\\ commit*) ;;
    *) exit 0 ;;
esac

# Run dotscope check on staged changes (30s timeout, fail open)
if command -v timeout >/dev/null 2>&1; then
    OUTPUT=$(timeout 30 python3 -m dotscope.cli check 2>&1) || true
elif command -v gtimeout >/dev/null 2>&1; then
    OUTPUT=$(gtimeout 30 python3 -m dotscope.cli check 2>&1) || true
else
    OUTPUT=$(python3 -m dotscope.cli check 2>&1) || true
fi

# Only GUARDs block. NUDGEs and NOTEs pass through.
if echo "$OUTPUT" | grep -qE "GUARD|HOLD"; then
    echo "$OUTPUT" >&2
    echo "" >&2
    echo "dotscope: commit blocked -- address guards before committing" >&2
    exit 2
fi

# NUDGEs and NOTEs are guidance, not gates
if echo "$OUTPUT" | grep -qE "NUDGE|NOTE"; then
    echo "$OUTPUT" >&2
fi

exit 0
"""


def install_claude_hook(repo_root: str) -> str:
    """Install Claude Code pre-commit enforcement hook.

    Creates .claude/hooks/pre-commit-check.sh and wires it into
    .claude/settings.json as a PreToolUse hook on Bash commands.

    Preserves existing settings.json content (permissions, other hooks).
    """
    claude_dir = os.path.join(repo_root, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    # Write the hook script
    script_path = os.path.join(hooks_dir, "pre-commit-check.sh")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(_HOOK_SCRIPT)
    try:
        os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)
    except OSError:
        pass

    # Load or create settings.json
    settings_path = os.path.join(claude_dir, "settings.json")
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            settings = {}

    # Add the hook (idempotent)
    hooks = settings.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])

    # Check if already installed
    hook_entry = {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": ".claude/hooks/pre-commit-check.sh",
            }
        ],
    }

    already = any(
        entry.get("matcher") == "Bash"
        and any(
            h.get("command", "").endswith("pre-commit-check.sh")
            for h in entry.get("hooks", [])
        )
        for entry in pre_tool
    )

    if not already:
        pre_tool.append(hook_entry)

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    return f"Claude Code hook installed: {script_path}"


_CLAUDE_MD_CONTENT = """\
# CLAUDE.md

This repo uses dotscope. Before touching code:

1. `codebase_search("your task description")` — not manual file reads
2. `dotscope_check` before every commit
3. If check returns HOLDs, fix them before committing

dotscope provides: dependency graph, implicit contracts, conventions,
and file locks. Use its tools instead of guessing.
"""

_CLAUDE_MD_SECTION = """
## dotscope

This repo uses dotscope. Before touching code:

1. `codebase_search("your task description")` — not manual file reads
2. `dotscope_check` before every commit
3. If check returns HOLDs, fix them before committing
"""


def write_claude_md(repo_root: str) -> str:
    """Write CLAUDE.md for automatic agent briefing.

    If CLAUDE.md doesn't exist, creates it with dotscope instructions.
    If it exists but has no dotscope section, appends one.
    If it already has a dotscope section, does nothing.
    """
    claude_md_path = os.path.join(repo_root, "CLAUDE.md")

    if not os.path.exists(claude_md_path):
        with open(claude_md_path, "w", encoding="utf-8") as f:
            f.write(_CLAUDE_MD_CONTENT)
        return f"Created {claude_md_path}"

    existing = open(claude_md_path, "r", encoding="utf-8").read()
    if "dotscope" in existing.lower() and "codebase_search" in existing:
        return "CLAUDE.md already has dotscope instructions"

    with open(claude_md_path, "a", encoding="utf-8") as f:
        f.write(_CLAUDE_MD_SECTION)
    return f"Appended dotscope section to {claude_md_path}"
