"""Git hook management for dotscope.

Two hooks:
  pre-commit  — routing verification. Runs dotscope check, blocks on GUARDs only.
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
_REFRESH_MARKER = "# dotscope refresh"
_POST_CHECKOUT_MARKER = "# dotscope post-checkout"
_POST_MERGE_MARKER = "# dotscope post-merge"
_PRE_MARKER = "# dotscope pre-commit"

# ---------------------------------------------------------------------------
# Pre-commit hook: routing verification (blocks on GUARDs only)
# ---------------------------------------------------------------------------

_PRE_COMMIT_SH = """\
#!/bin/sh
# dotscope pre-commit
# Runs dotscope check on staged changes. Only GUARDs block the commit.
# NUDGEs and NOTEs print but pass through.
# Timeout after 30 seconds — fail open if dotscope hangs.
if command -v timeout >/dev/null 2>&1; then
    OUTPUT=$(timeout 30 python3 -m dotscope.cli check 2>&1) || true
elif command -v gtimeout >/dev/null 2>&1; then
    OUTPUT=$(gtimeout 30 python3 -m dotscope.cli check 2>&1) || true
else
    OUTPUT=$(python3 -m dotscope.cli check 2>&1) || true
fi
if echo "$OUTPUT" | grep -qE "GUARD|HOLD"; then
    echo "$OUTPUT" >&2
    echo "" >&2
    echo "dotscope: commit blocked -- address guards before committing" >&2
    exit 1
fi
if echo "$OUTPUT" | grep -qE "NUDGE|NOTE"; then
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
    if "GUARD" in output or "HOLD" in output:
        print(output, file=sys.stderr)
        print("", file=sys.stderr)
        print("dotscope: commit blocked -- address guards before committing", file=sys.stderr)
        sys.exit(1)
    if "NUDGE" in output or "NOTE" in output:
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
# Capture observation output for agent feedback (Gap 4)
OUTPUT=$(python3 -m dotscope.cli observe "$COMMIT_HASH" 2>&1) || true
if [ -n "$OUTPUT" ]; then
    echo "$OUTPUT" >&2
fi
# dotscope incremental
python3 -m dotscope.cli incremental "$COMMIT_HASH" 2>/dev/null || true
# dotscope refresh
python3 -m dotscope.cli refresh enqueue --commit "$COMMIT_HASH" 2>/dev/null || true
python3 -m dotscope.cli refresh run --drain 2>/dev/null || true &
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
        # dotscope refresh
        subprocess.run([sys.executable, "-m", "dotscope.cli", "refresh", "enqueue", "--commit", commit],
                       timeout=30, capture_output=True)
        # NOTE: Intentionally fire-and-forget — worker self-terminates via queue drain.
        subprocess.Popen([sys.executable, "-m", "dotscope.cli", "refresh", "run", "--drain"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass  # Never block commits
"""

_POST_CHECKOUT_SH = """\
#!/bin/sh
# dotscope post-checkout
if [ "$3" = "1" ]; then
    python3 -m dotscope.cli refresh enqueue --repo --reason "branch switch" 2>/dev/null || true
    python3 -m dotscope.cli refresh run --drain 2>/dev/null || true &
fi
"""

_POST_CHECKOUT_PY = """\
#!/usr/bin/env python3
# dotscope post-checkout
import subprocess, sys
try:
    if len(sys.argv) >= 4 and sys.argv[3] == "1":
        subprocess.run([sys.executable, "-m", "dotscope.cli", "refresh", "enqueue", "--repo", "--reason", "branch switch"],
                       timeout=30, capture_output=True)
        # NOTE: Intentionally fire-and-forget — worker self-terminates via queue drain.
        subprocess.Popen([sys.executable, "-m", "dotscope.cli", "refresh", "run", "--drain"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass
"""

_POST_MERGE_SH = """\
#!/bin/sh
# dotscope post-merge
python3 -m dotscope.cli refresh enqueue --repo --reason "post-merge" 2>/dev/null || true
python3 -m dotscope.cli refresh run --drain 2>/dev/null || true &
"""

_POST_MERGE_PY = """\
#!/usr/bin/env python3
# dotscope post-merge
import subprocess, sys
try:
    subprocess.run([sys.executable, "-m", "dotscope.cli", "refresh", "enqueue", "--repo", "--reason", "post-merge"],
                   timeout=30, capture_output=True)
    # NOTE: Intentionally fire-and-forget — worker self-terminates via queue drain.
    subprocess.Popen([sys.executable, "-m", "dotscope.cli", "refresh", "run", "--drain"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass
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
                         or line.strip().startswith("pass")
                         or line.strip().startswith("commit =")
                         or line.strip().startswith("Popen(")):
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
                    'python3 -m dotscope.cli incremental "$COMMIT_HASH" 2>/dev/null || true\n'
                )
                with open(post_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{incremental_line}")
            if _REFRESH_MARKER not in existing:
                refresh_block = (
                    '# dotscope refresh\n'
                    'python3 -m dotscope.cli refresh enqueue --commit "$COMMIT_HASH" 2>/dev/null || true\n'
                    'python3 -m dotscope.cli refresh run --drain 2>/dev/null || true &\n'
                )
                with open(post_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{refresh_block}")
            results.append(f"post-commit: {post_path} (existing, upgraded)")
        else:
            path = _write_hook(post_path, post_content, _POST_MARKER)
            results.append(f"post-commit: {path}")
    else:
        path = _write_hook(post_path, post_content, _POST_MARKER)
        results.append(f"post-commit: {path}")

    checkout_path = hooks_dir / "post-checkout"
    checkout_content = _POST_CHECKOUT_PY if _is_windows_native() else _POST_CHECKOUT_SH
    path = _write_hook(checkout_path, checkout_content, _POST_CHECKOUT_MARKER)
    results.append(f"post-checkout: {path}")

    merge_path = hooks_dir / "post-merge"
    merge_content = _POST_MERGE_PY if _is_windows_native() else _POST_MERGE_SH
    path = _write_hook(merge_path, merge_content, _POST_MERGE_MARKER)
    results.append(f"post-merge: {path}")

    # AST merge driver registration
    merge_result = install_merge_driver(repo_root)
    if merge_result:
        results.append(merge_result)

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
    removed |= _remove_hook_lines(hooks_dir / "post-commit", _REFRESH_MARKER)
    removed |= _remove_hook_lines(hooks_dir / "post-checkout", _POST_CHECKOUT_MARKER)
    removed |= _remove_hook_lines(hooks_dir / "post-merge", _POST_MERGE_MARKER)

    return removed


def is_hook_installed(repo_root: str) -> bool:
    """Check if dotscope hooks are installed."""
    hooks_dir = Path(repo_root) / ".git" / "hooks"

    pre_installed = False
    post_installed = False
    checkout_installed = False
    merge_installed = False

    pre_path = hooks_dir / "pre-commit"
    if pre_path.exists():
        pre_installed = _PRE_MARKER in pre_path.read_text(encoding="utf-8")

    post_path = hooks_dir / "post-commit"
    if post_path.exists():
        post_installed = _POST_MARKER in post_path.read_text(encoding="utf-8")

    checkout_path = hooks_dir / "post-checkout"
    if checkout_path.exists():
        checkout_installed = _POST_CHECKOUT_MARKER in checkout_path.read_text(encoding="utf-8")

    merge_path = hooks_dir / "post-merge"
    if merge_path.exists():
        merge_installed = _POST_MERGE_MARKER in merge_path.read_text(encoding="utf-8")

    return pre_installed or post_installed or checkout_installed or merge_installed


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

    checkout_path = hooks_dir / "post-checkout"
    if checkout_path.exists() and _POST_CHECKOUT_MARKER in checkout_path.read_text(encoding="utf-8"):
        parts.append("post-checkout: installed (branch refresh)")
    else:
        parts.append("post-checkout: not installed")

    merge_path = hooks_dir / "post-merge"
    if merge_path.exists() and _POST_MERGE_MARKER in merge_path.read_text(encoding="utf-8"):
        parts.append("post-merge: installed (merge refresh)")
    else:
        parts.append("post-merge: not installed")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# AST Merge Driver: scope-aware .gitattributes wiring
# ---------------------------------------------------------------------------

_GITATTRIBUTES_MARKER = "# dotscope AST merge driver"
_MERGE_DRIVER_NAME = "dotscope-ast"


def install_merge_driver(repo_root: str) -> str:
    """Register the AST merge driver in .git/config and generate .gitattributes.

    Only files actively analyzed by dotscope (matching scope includes)
    receive the custom merge driver. Unscoped files fall through to
    Git's default line-level merger.
    """
    import subprocess

    git_dir = Path(repo_root) / ".git"
    if not git_dir.is_dir():
        return ""

    # Register the driver in .git/config
    driver_cmd = "python3 -m dotscope.merge.driver %O %A %B"
    try:
        subprocess.run(
            ["git", "config", f"merge.{_MERGE_DRIVER_NAME}.driver", driver_cmd],
            cwd=repo_root, capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "config", f"merge.{_MERGE_DRIVER_NAME}.name",
             "dotscope AST-aware semantic merge"],
            cwd=repo_root, capture_output=True, timeout=5,
        )
    except Exception:
        return ""

    # Generate .gitattributes from active scopes
    _update_gitattributes(repo_root)

    return f"merge-driver: {_MERGE_DRIVER_NAME} registered"


def _update_gitattributes(repo_root: str) -> None:
    """Write scope-aware .gitattributes entries for the AST merge driver.

    Scans .scope files to find which file patterns dotscope actively
    analyzes. Only those patterns get the custom merge driver — everything
    else uses Git's default.
    """
    from ..discovery import find_all_scopes
    from ..parser import parse_scope_file

    scope_files = find_all_scopes(repo_root)
    patterns = set()

    for sf in scope_files:
        try:
            config = parse_scope_file(sf)
            for inc in config.includes:
                # Convert scope includes to gitattributes glob patterns
                if inc.endswith("/"):
                    # Directory pattern → all source files under it
                    patterns.add(f"{inc}*.py merge={_MERGE_DRIVER_NAME}")
                    patterns.add(f"{inc}*.ts merge={_MERGE_DRIVER_NAME}")
                    patterns.add(f"{inc}*.js merge={_MERGE_DRIVER_NAME}")
                elif inc.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go")):
                    patterns.add(f"{inc} merge={_MERGE_DRIVER_NAME}")
                elif "*" in inc or "?" in inc:
                    patterns.add(f"{inc} merge={_MERGE_DRIVER_NAME}")
        except Exception:
            continue

    if not patterns:
        return

    # Write .gitattributes (preserve existing non-dotscope entries)
    attr_path = Path(repo_root) / ".gitattributes"
    existing_lines = []
    if attr_path.exists():
        existing_lines = [
            line for line in attr_path.read_text(encoding="utf-8").splitlines()
            if _MERGE_DRIVER_NAME not in line and _GITATTRIBUTES_MARKER not in line
        ]

    dotscope_block = [_GITATTRIBUTES_MARKER]
    dotscope_block.extend(sorted(patterns))

    all_lines = existing_lines + [""] + dotscope_block if existing_lines else dotscope_block
    attr_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")


def uninstall_merge_driver(repo_root: str) -> bool:
    """Remove the AST merge driver from .git/config and .gitattributes."""
    import subprocess
    removed = False

    try:
        subprocess.run(
            ["git", "config", "--remove-section", f"merge.{_MERGE_DRIVER_NAME}"],
            cwd=repo_root, capture_output=True, timeout=5,
        )
        removed = True
    except Exception:
        pass

    attr_path = Path(repo_root) / ".gitattributes"
    if attr_path.exists():
        lines = attr_path.read_text(encoding="utf-8").splitlines()
        filtered = [
            line for line in lines
            if _MERGE_DRIVER_NAME not in line and _GITATTRIBUTES_MARKER not in line
        ]
        if len(filtered) < len(lines):
            attr_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
            removed = True

    return removed
