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
    git\ commit*) ;;
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

# Parse result: if "hold" appears, block the commit
if echo "$OUTPUT" | grep -q "HOLD"; then
    echo "$OUTPUT" >&2
    echo "" >&2
    echo "dotscope: commit blocked -- address holds before committing" >&2
    exit 2
fi

# Notes are informational, don't block
if echo "$OUTPUT" | grep -q "NOTE"; then
    echo "$OUTPUT" >&2
fi

exit 0
