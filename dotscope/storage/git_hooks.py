"""Git hook management for dotscope.

Two hooks:
  pre-commit  — enforcement. Runs dotscope check, blocks on HOLDs.
  post-commit — feedback loop. Runs observe + incremental, never blocks.

Both are deliberately minimal. All logic lives in Python.

On Windows (no /bin/sh), we write Python-based hooks instead.
Git for Windows invokes extensionless hook files via its bundled sh,
but we also handle the pure-Windows case.
"""

import os
import stat
import sys
from pathlib import Path

_POST_MARKER = "# dotscope auto-observer"
_INCREMENTAL_MARKER = "# dotscope incremental"
_PRE_MARKER = "# dotscope pre-commit"

# ---------------------------------------------------------------------------
# Pre-commit hook: enforcement (blocks on HOLDs)
# ---------------------------------------------------------------------------

_PRE_COMMIT_SH = """\
#!/bin/sh
# dotscope pre-commit
# Runs dotscope check on staged changes. HOLDs block the commit.
# Timeout after 30 seconds — fail open if dotscope hangs.
if command -v timeout >/dev/null 2>&1; then
    OUTPUT=$(timeout 30 python -m dotscope.cli check 2>&1) || true
elif command -v gtimeout >/dev/null 2>&1; then
    OUTPUT=$(gtimeout 30 python -m dotscope.cli check 2>&1) || true
else
    OUTPUT=$(python -m dotscope.cli check 2>&1) || true
fi
if echo "$OUTPUT" | grep -q "HOLD"; then
    echo "$OUTPUT" >&2
    echo "" >&2
    echo "dotscope: commit blocked -- address holds before committing" >&2
    exit 1
fi
if echo "$OUTPUT" | grep -q "NOTE"; then
    echo "$OUTPUT" >&2
fi
"""

_PRE_COMMIT_PY = """\
#!/usr/bin/env python3
# dotscope pre-commit
import subprocess, sys
try:
    result = subprocess.run(
        [sys.executable, "-m", "dotscope.cli", "check"],
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    if "HOLD" in output:
        print(output, file=sys.stderr)
        print("", file=sys.stderr)
        print("dotscope: commit blocked -- address holds before committing", file=sys.stderr)
        sys.exit(1)
    if "NOTE" in output:
        print(output, file=sys.stderr)
except Exception:
    pass  # If dotscope fails, don't block
"""

# ---------------------------------------------------------------------------
# Post-commit hook: feedback loop (never blocks)
# ---------------------------------------------------------------------------

_POST_COMMIT_SH = """\
#!/bin/sh
# dotscope auto-observer
COMMIT_HASH=$(git rev-parse HEAD)
python -m dotscope.cli observe "$COMMIT_HASH" 2>/dev/null || true
# dotscope incremental
python -m dotscope.cli incremental "$COMMIT_HASH" 2>/dev/null || true
"""

_POST_COMMIT_PY = """\
#!/usr/bin/env python3
# dotscope auto-observer
import subprocess, sys
try:
    result = subprocess.run(["git", "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        commit = result.stdout.strip()
        subprocess.run([sys.executable, "-m", "dotscope.cli", "observe", commit],
                       timeout=30, capture_output=True)
        # dotscope incremental
        subprocess.run([sys.executable, "-m", "dotscope.cli", "incremental", commit],
                       timeout=30, capture_output=True)
except Exception:
    pass  # Never block commits
"""


def _is_windows_native() -> bool:
    """True if running on Windows without Git Bash / MSYS2 / WSL."""
    if os.name != "nt":
        return False
    return not (os.environ.get("MSYSTEM") or os.environ.get("SHELL"))


def _write_hook(hook_path: Path, content: str, marker: str) -> str:
    """Write or append a hook file. Returns the path as string."""
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if marker in existing:
            return str(hook_path)  # Already installed
        # Append to existing hook
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write(f"\n{content}")
    else:
        hook_path.write_text(content, encoding="utf-8")

    # Make executable
    try:
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
    except OSError:
        pass

    return str(hook_path)


def _remove_hook_lines(hook_path: Path, marker: str) -> bool:
    """Remove lines associated with a marker from a hook file."""
    if not hook_path.exists():
        return False

    content = hook_path.read_text(encoding="utf-8")
    if marker not in content:
        return False

    lines = content.splitlines()
    filtered = []
    in_block = False
    for line in lines:
        if marker in line:
            in_block = True
            continue
        if in_block and ("dotscope" in line or "COMMIT_HASH" in line
                         or "subprocess" in line or "OUTPUT" in line
                         or line.strip().startswith("if ") or line.strip().startswith("echo ")
                         or line.strip().startswith("exit ") or line.strip().startswith("fi")
                         or line.strip().startswith("print(") or line.strip().startswith("sys.exit")
                         or line.strip().startswith("result =") or line.strip().startswith("output =")
                         or line.strip().startswith("except") or line.strip().startswith("try:")
                         or line.strip().startswith("pass")):
            continue
        in_block = False
        filtered.append(line)

    remaining = "\n".join(filtered).strip()
    shebang_only = remaining in ("#!/bin/sh", "#!/usr/bin/env python3")
    if not remaining or shebang_only:
        hook_path.unlink()
    else:
        hook_path.write_text(remaining + "\n", encoding="utf-8")

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_hook(repo_root: str) -> str:
    """Install both pre-commit and post-commit hooks. Returns summary."""
    hooks_dir = Path(repo_root) / ".git" / "hooks"
    results = []

    # Pre-commit (enforcement)
    pre_path = hooks_dir / "pre-commit"
    if _is_windows_native():
        pre_content = _PRE_COMMIT_PY
    else:
        pre_content = _PRE_COMMIT_SH
    path = _write_hook(pre_path, pre_content, _PRE_MARKER)
    results.append(f"pre-commit: {path}")

    # Post-commit (feedback loop)
    post_path = hooks_dir / "post-commit"
    if _is_windows_native():
        post_content = _POST_COMMIT_PY
    else:
        post_content = _POST_COMMIT_SH

    if post_path.exists():
        existing = post_path.read_text(encoding="utf-8")
        if _POST_MARKER in existing:
            # Upgrade: add incremental line if missing
            if _INCREMENTAL_MARKER not in existing:
                incremental_line = (
                    '# dotscope incremental\n'
                    'python -m dotscope.cli incremental "$COMMIT_HASH" 2>/dev/null || true\n'
                )
                with open(post_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{incremental_line}")
            results.append(f"post-commit: {post_path} (existing, upgraded)")
        else:
            path = _write_hook(post_path, post_content, _POST_MARKER)
            results.append(f"post-commit: {path}")
    else:
        path = _write_hook(post_path, post_content, _POST_MARKER)
        results.append(f"post-commit: {path}")

    # Onboarding
    try:
        from .onboarding import mark_milestone
        mark_milestone(repo_root, "hook_installed")
    except Exception:
        pass

    return "\n".join(results)


def uninstall_hook(repo_root: str) -> bool:
    """Remove dotscope from both hook files. Returns True if anything removed."""
    hooks_dir = Path(repo_root) / ".git" / "hooks"
    removed = False

    removed |= _remove_hook_lines(hooks_dir / "pre-commit", _PRE_MARKER)
    removed |= _remove_hook_lines(hooks_dir / "post-commit", _POST_MARKER)
    removed |= _remove_hook_lines(hooks_dir / "post-commit", _INCREMENTAL_MARKER)

    return removed


def is_hook_installed(repo_root: str) -> bool:
    """Check if dotscope hooks are installed."""
    hooks_dir = Path(repo_root) / ".git" / "hooks"

    pre_installed = False
    post_installed = False

    pre_path = hooks_dir / "pre-commit"
    if pre_path.exists():
        pre_installed = _PRE_MARKER in pre_path.read_text(encoding="utf-8")

    post_path = hooks_dir / "post-commit"
    if post_path.exists():
        post_installed = _POST_MARKER in post_path.read_text(encoding="utf-8")

    return pre_installed or post_installed


def hook_status(repo_root: str) -> str:
    """Return a human-readable hook status."""
    hooks_dir = Path(repo_root) / ".git" / "hooks"
    parts = []

    pre_path = hooks_dir / "pre-commit"
    if pre_path.exists() and _PRE_MARKER in pre_path.read_text(encoding="utf-8"):
        parts.append("pre-commit: installed (enforcement)")
    else:
        parts.append("pre-commit: not installed")

    post_path = hooks_dir / "post-commit"
    if post_path.exists() and _POST_MARKER in post_path.read_text(encoding="utf-8"):
        parts.append("post-commit: installed (feedback loop)")
    else:
        parts.append("post-commit: not installed")

    return "\n".join(parts)
