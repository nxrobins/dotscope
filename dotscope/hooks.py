"""Git hook management for dotscope auto-observation.

The post-commit hook calls `dotscope observe HEAD` after every commit,
closing the feedback loop between scope predictions and actual changes.

The hook is deliberately minimal. All logic lives in Python.
Failures never block commits (|| true).
"""

import stat
from pathlib import Path

_HOOK_MARKER = "# dotscope auto-observer"

_HOOK_CONTENT = """\
#!/bin/sh
# dotscope auto-observer
COMMIT_HASH=$(git rev-parse HEAD)
python -m dotscope.cli observe "$COMMIT_HASH" 2>/dev/null || true
"""


def install_hook(repo_root: str) -> str:
    """Install the post-commit hook. Returns the hook path.

    If a post-commit hook already exists, appends the dotscope observer
    rather than overwriting.
    """
    hook_path = Path(repo_root) / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _HOOK_MARKER in existing:
            return str(hook_path)  # Already installed

        # Append to existing hook
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write(f"\n{_HOOK_CONTENT}")
    else:
        hook_path.write_text(_HOOK_CONTENT, encoding="utf-8")

    # Make executable
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
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
        if skip_next and ("dotscope" in line or "COMMIT_HASH" in line):
            continue
        skip_next = False
        filtered.append(line)

    remaining = "\n".join(filtered).strip()
    if not remaining or remaining == "#!/bin/sh":
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
