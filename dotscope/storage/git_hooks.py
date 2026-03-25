"""Git hook management for dotscope auto-observation.

The post-commit hook calls `dotscope observe HEAD` after every commit,
closing the feedback loop between scope predictions and actual changes.

The hook is deliberately minimal. All logic lives in Python.
Failures never block commits.

On Windows (no /bin/sh), we write a Python-based hook instead.
Git for Windows invokes extensionless hook files via its bundled sh,
but we also handle the pure-Windows case.
"""

import os
import stat
import sys
from pathlib import Path

_HOOK_MARKER = "# dotscope auto-observer"

# POSIX hook (Linux, macOS, Git Bash on Windows)
_HOOK_CONTENT_SH = """\
#!/bin/sh
# dotscope auto-observer
COMMIT_HASH=$(git rev-parse HEAD)
python -m dotscope.cli observe "$COMMIT_HASH" 2>/dev/null || true
"""

# Python hook (Windows without sh)
_HOOK_CONTENT_PY = """\
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
except Exception:
    pass  # Never block commits
"""


def _pick_hook_content() -> str:
    """Choose hook content based on platform."""
    if os.name == "nt":
        # Check if running under Git Bash / MSYS2 / WSL
        if os.environ.get("MSYSTEM") or os.environ.get("SHELL"):
            return _HOOK_CONTENT_SH
        return _HOOK_CONTENT_PY
    return _HOOK_CONTENT_SH


def install_hook(repo_root: str) -> str:
    """Install the post-commit hook. Returns the hook path.

    If a post-commit hook already exists, appends the dotscope observer
    rather than overwriting.
    """
    hook_path = Path(repo_root) / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    content = _pick_hook_content()

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _HOOK_MARKER in existing:
            return str(hook_path)  # Already installed

        # Append to existing hook
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write(f"\n{content}")
    else:
        hook_path.write_text(content, encoding="utf-8")

    # Make executable (no-op on Windows, required on POSIX)
    try:
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
    except OSError:
        pass  # Windows may not support chmod

    # Onboarding: mark hook installed
    try:
        from ..onboarding import mark_milestone
        mark_milestone(repo_root, "hook_installed")
    except Exception:
        pass

    return str(hook_path)


def uninstall_hook(repo_root: str) -> bool:
    """Remove the dotscope observer from the post-commit hook.

    If the hook only contains the dotscope observer, removes the file.
    If it contains other hooks too, removes only the dotscope lines.
    Returns True if something was removed.
    """
    hook_path = Path(repo_root) / ".git" / "hooks" / "post-commit"
    if not hook_path.exists():
        return False

    content = hook_path.read_text(encoding="utf-8")
    if _HOOK_MARKER not in content:
        return False

    # Remove dotscope lines
    lines = content.splitlines()
    filtered = []
    skip_next = False
    for line in lines:
        if _HOOK_MARKER in line:
            skip_next = True
            continue
        if skip_next and ("dotscope" in line or "COMMIT_HASH" in line or "subprocess" in line):
            continue
        skip_next = False
        filtered.append(line)

    remaining = "\n".join(filtered).strip()
    shebang_only = remaining in ("#!/bin/sh", "#!/usr/bin/env python3")
    if not remaining or shebang_only:
        hook_path.unlink()
    else:
        hook_path.write_text(remaining + "\n", encoding="utf-8")

    return True


def is_hook_installed(repo_root: str) -> bool:
    """Check if the dotscope post-commit hook is installed."""
    hook_path = Path(repo_root) / ".git" / "hooks" / "post-commit"
    if not hook_path.exists():
        return False
    return _HOOK_MARKER in hook_path.read_text(encoding="utf-8")
