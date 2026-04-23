"""Cross-platform advisory file locks for short-lived mutation guards."""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .atomic import atomic_write_json, read_json_with_retry

if os.name == "nt":  # pragma: no cover - exercised on Windows
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:  # pragma: no cover - exercised on POSIX
    import fcntl


@dataclass(frozen=True)
class LockMetadata:
    pid: int
    process_start_time: str | None
    acquired_at: str


class FileLockTimeoutError(TimeoutError):
    """Raised when a lock could not be acquired before the timeout."""


@contextmanager
def exclusive_file_lock(
    path: str | os.PathLike[str],
    *,
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.1,
) -> Iterator[LockMetadata]:
    """Acquire an exclusive advisory lock backed by an OS file descriptor."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = open(target, "a+b")
    _ensure_lockfile_seeded(handle)
    acquired = False
    waited_on_live_holder_since: float | None = None
    metadata = LockMetadata(
        pid=os.getpid(),
        process_start_time=_process_start_time_token(os.getpid()),
        acquired_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        while True:
            try:
                _acquire_lock(handle)
                acquired = True
                break
            except BlockingIOError as exc:
                holder = _read_lock_metadata(target)
                if holder is not None and not _holder_is_alive(holder):
                    _remove_lock_metadata(target)
                    waited_on_live_holder_since = None
                else:
                    if waited_on_live_holder_since is None:
                        waited_on_live_holder_since = time.monotonic()
                    elif time.monotonic() - waited_on_live_holder_since >= timeout_seconds:
                        raise FileLockTimeoutError(_format_lock_timeout(target, holder)) from exc
                time.sleep(poll_interval)

        _write_lock_metadata(target, metadata)
        yield metadata
    finally:
        if acquired:
            _remove_lock_metadata(target, owner=metadata)
            _release_lock(handle)
        handle.close()


def _ensure_lockfile_seeded(handle) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()


def _lock_metadata_path(path: str | os.PathLike[str]) -> Path:
    target = Path(path)
    return target.with_name(f"{target.name}.meta.json")


def _read_lock_metadata(path: str | os.PathLike[str]) -> LockMetadata | None:
    metadata_path = _lock_metadata_path(path)
    if not metadata_path.exists():
        return None

    try:
        payload = read_json_with_retry(metadata_path)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    try:
        return LockMetadata(**payload)
    except TypeError:
        return None


def _write_lock_metadata(path: str | os.PathLike[str], metadata: LockMetadata) -> None:
    atomic_write_json(_lock_metadata_path(path), asdict(metadata))


def _remove_lock_metadata(
    path: str | os.PathLike[str],
    *,
    owner: LockMetadata | None = None,
) -> None:
    metadata_path = _lock_metadata_path(path)
    if not metadata_path.exists():
        return

    if owner is not None:
        current = _read_lock_metadata(path)
        if current is not None and current != owner:
            return

    try:
        metadata_path.unlink()
    except OSError:
        pass


def _holder_is_alive(holder: LockMetadata) -> bool:
    if holder.pid <= 0:
        return False

    current = _process_start_time_token(holder.pid)
    if current is None:
        return False
    if holder.process_start_time is None:
        return True
    return current == holder.process_start_time


def _format_lock_timeout(path: Path, holder: LockMetadata | None) -> str:
    if holder is None:
        return f"Timed out acquiring lock: {path}"
    return (
        f"Timed out acquiring lock: {path} "
        f"(held by pid {holder.pid}, started {holder.process_start_time or 'unknown'})"
    )


def _process_start_time_token(pid: int) -> str | None:
    if pid <= 0:
        return None

    if os.name == "nt":  # pragma: no cover - exercised on Windows
        return _process_start_time_windows(pid)
    return _process_start_time_posix(pid)


def _process_start_time_posix(pid: int) -> str | None:
    proc_dir = Path("/proc") / str(pid)
    if proc_dir.exists():
        try:
            return str(proc_dir.stat().st_ctime_ns)
        except OSError:
            return None

    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    return text or None


def _process_start_time_windows(pid: int) -> str | None:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value != STILL_ACTIVE:
            return None

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return str(value)
    finally:
        kernel32.CloseHandle(handle)


def _acquire_lock(handle) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc
        return

    try:  # pragma: no cover - exercised on POSIX
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise BlockingIOError(str(exc)) from exc


def _release_lock(handle) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # pragma: no cover - exercised on POSIX
