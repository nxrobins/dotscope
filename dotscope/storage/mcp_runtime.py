"""Managed dotscope-owned MCP runtime installation and state."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import __version__
from .atomic import atomic_write_json


@dataclass(frozen=True)
class McpLaunchSpec:
    """A concrete launcher that can start the dotscope MCP server."""

    command: str
    args: tuple[str, ...]
    source: str

    def argv(self, repo_root: str) -> list[str]:
        return [
            self.command,
            *self.args,
            "--root",
            os.path.abspath(repo_root),
        ]


@dataclass(frozen=True)
class ManagedRuntimeState:
    """Persisted metadata for a managed MCP runtime install."""

    dotscope_version: str
    runtime_root: str
    python_executable: str
    launcher_path: str
    package_spec: str
    package_source: str
    installed_at: str


def ensure_managed_mcp_runtime(
    repo_root: str,
    *,
    probe_func: Callable[[McpLaunchSpec, str], dict],
) -> tuple[McpLaunchSpec, dict]:
    """Install or repair the managed MCP runtime and verify it."""
    repo_root = os.path.abspath(repo_root)
    runtime_root = managed_runtime_root()
    desired_spec, desired_source = resolve_managed_package_spec()
    launcher = managed_runtime_launcher_spec()
    state = load_managed_runtime_state()

    if _managed_runtime_matches(state, launcher, desired_spec, desired_source):
        probe = probe_func(launcher, repo_root)
        if probe.get("ok"):
            return launcher, _managed_runtime_report(
                status="ok",
                state=state,
                probe=probe,
                desired_spec=desired_spec,
                desired_source=desired_source,
            )

    _rebuild_managed_runtime(runtime_root)
    python_executable = managed_runtime_python_path(runtime_root)
    _install_runtime_package(python_executable, desired_spec)

    state = ManagedRuntimeState(
        dotscope_version=__version__,
        runtime_root=str(runtime_root),
        python_executable=str(python_executable),
        launcher_path=launcher.command,
        package_spec=desired_spec,
        package_source=desired_source,
        installed_at=datetime.now(timezone.utc).isoformat(),
    )
    save_managed_runtime_state(state)

    probe = probe_func(launcher, repo_root)
    if not probe.get("ok"):
        raise RuntimeError(
            "Managed dotscope MCP runtime was installed but failed verification: "
            f"{probe.get('error', 'unknown error')}"
        )

    return launcher, _managed_runtime_report(
        status="ok",
        state=state,
        probe=probe,
        desired_spec=desired_spec,
        desired_source=desired_source,
    )


def diagnose_managed_mcp_runtime(
    repo_root: str,
    *,
    probe_func: Callable[[McpLaunchSpec, str], dict],
) -> dict:
    """Report managed runtime status without mutating state."""
    repo_root = os.path.abspath(repo_root)
    launcher = managed_runtime_launcher_spec()
    state = load_managed_runtime_state()
    desired_spec, desired_source = resolve_managed_package_spec()
    runtime_root = managed_runtime_root()

    status = "missing"
    probe = None
    if state and Path(launcher.command).exists():
        if _managed_runtime_matches(state, launcher, desired_spec, desired_source):
            probe = probe_func(launcher, repo_root)
            status = "ok" if probe.get("ok") else "broken"
        else:
            status = "stale"

    report = _managed_runtime_report(
        status=status,
        state=state,
        probe=probe,
        desired_spec=desired_spec,
        desired_source=desired_source,
    )
    report["runtime_root"] = str(runtime_root)
    report["state_path"] = str(managed_runtime_state_path())
    report["launcher_path"] = launcher.command
    return report


def managed_runtime_root() -> Path:
    """Return the owned MCP runtime directory for the current dotscope version."""
    override = os.environ.get("DOTSCOPE_MCP_RUNTIME_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return (base / "dotscope" / "mcp-runtime" / __version__).resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "dotscope" / "mcp-runtime" / __version__).resolve()

    xdg_data = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data).expanduser() if xdg_data else (Path.home() / ".local" / "share")
    return (base / "dotscope" / "mcp-runtime" / __version__).resolve()


def managed_runtime_state_path() -> Path:
    return managed_runtime_root() / "install.json"


def managed_runtime_python_path(runtime_root: Path | None = None) -> Path:
    root = runtime_root or managed_runtime_root()
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def managed_runtime_launcher_path(runtime_root: Path | None = None) -> Path:
    root = runtime_root or managed_runtime_root()
    if os.name == "nt":
        return root / "Scripts" / "dotscope-mcp.exe"
    return root / "bin" / "dotscope-mcp"


def managed_runtime_launcher_spec() -> McpLaunchSpec:
    return McpLaunchSpec(
        command=str(managed_runtime_launcher_path()),
        args=(),
        source="managed-runtime",
    )


def load_managed_runtime_state() -> ManagedRuntimeState | None:
    path = managed_runtime_state_path()
    if not path.exists():
        return None

    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    try:
        return ManagedRuntimeState(**payload)
    except TypeError:
        return None


def save_managed_runtime_state(state: ManagedRuntimeState) -> None:
    atomic_write_json(managed_runtime_state_path(), asdict(state))


def resolve_managed_package_spec() -> tuple[str, str]:
    """Return the package requirement or direct reference for runtime installation."""
    override = os.environ.get("DOTSCOPE_MCP_PACKAGE_SPEC")
    if override:
        return override, "env-override"

    project_root = _detect_source_project_root()
    if project_root is not None:
        return f"dotscope[mcp] @ {project_root.as_uri()}", "local-source"

    return f"dotscope[mcp]=={__version__}", "published"


def _detect_source_project_root() -> Path | None:
    package_root = Path(__file__).resolve().parents[2]
    pyproject = package_root / "pyproject.toml"
    if pyproject.exists():
        return package_root
    return None


def _managed_runtime_matches(
    state: ManagedRuntimeState | None,
    launcher: McpLaunchSpec,
    desired_spec: str,
    desired_source: str,
) -> bool:
    if state is None:
        return False
    if state.dotscope_version != __version__:
        return False
    if state.package_spec != desired_spec or state.package_source != desired_source:
        return False
    if state.launcher_path != launcher.command:
        return False
    if not Path(state.python_executable).exists():
        return False
    if not Path(launcher.command).exists():
        return False
    return True


def _rebuild_managed_runtime(runtime_root: Path) -> None:
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    builder = venv.EnvBuilder(with_pip=True, clear=True)
    builder.create(str(runtime_root))


def _install_runtime_package(python_executable: Path, package_spec: str) -> None:
    install_env = os.environ.copy()
    install_env.setdefault("PYTHONUTF8", "1")
    install_env.setdefault("PYTHONIOENCODING", "utf-8")
    install_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    bootstrap = [
        str(python_executable),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "setuptools",
        "wheel",
    ]
    _run_install_command(bootstrap, env=install_env)

    install = [
        str(python_executable),
        "-m",
        "pip",
        "install",
        "--upgrade",
        package_spec,
    ]
    _run_install_command(install, env=install_env)


def _run_install_command(command: list[str], *, env: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode == 0:
        return

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    details = stderr or stdout or f"exit code {completed.returncode}"
    if len(details) > 600:
        details = details[-600:]
    raise RuntimeError(f"Managed MCP runtime install failed: {details}")


def _managed_runtime_report(
    *,
    status: str,
    state: ManagedRuntimeState | None,
    probe: dict | None,
    desired_spec: str,
    desired_source: str,
) -> dict:
    return {
        "status": status,
        "desired_package_spec": desired_spec,
        "desired_package_source": desired_source,
        "installed": state is not None,
        "installed_at": state.installed_at if state else None,
        "package_spec": state.package_spec if state else None,
        "package_source": state.package_source if state else None,
        "python_executable": state.python_executable if state else None,
        "probe": probe,
    }
