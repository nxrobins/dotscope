"""Atomic persistence helpers for dotscope machine state."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write a text file atomically by replacing it after a flushed temp write."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str | os.PathLike[str],
    payload: Any,
    *,
    indent: int = 2,
) -> None:
    """Serialize JSON to disk atomically."""
    atomic_write_text(
        path,
        json.dumps(payload, indent=indent),
        encoding="utf-8",
    )


def read_text_with_retry(
    path: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    attempts: int = 5,
    delay_seconds: float = 0.05,
) -> str:
    """Read text with a short retry window for transient Windows sharing violations."""
    target = Path(path)
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            return target.read_text(encoding=encoding)
        except OSError as exc:
            if not _is_transient_read_error(exc) or attempt == attempts - 1:
                raise
            last_error = exc
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error
    raise FileNotFoundError(target)


def read_json_with_retry(
    path: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
) -> Any:
    """Read JSON from disk with transient-read retries."""
    return json.loads(read_text_with_retry(path, encoding=encoding))


def _fsync_directory(path: Path) -> None:
    """Best-effort directory sync after an atomic replace."""
    if os.name == "nt":
        return

    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return

    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _is_transient_read_error(exc: OSError) -> bool:
    if os.name != "nt":
        return False
    return exc.winerror in {32, 33} or exc.errno in {13}
