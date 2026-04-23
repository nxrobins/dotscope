from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dotscope.storage.atomic import read_text_with_retry
from dotscope.storage.file_lock import (
    FileLockTimeoutError,
    _lock_metadata_path,
    _read_lock_metadata,
    exclusive_file_lock,
)


def test_stale_lock_metadata_is_rewritten(tmp_path):
    lock_path = tmp_path / "boot.lock"
    metadata_path = _lock_metadata_path(lock_path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "pid": 999999,
                "process_start_time": "stale",
                "acquired_at": "2026-04-22T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with exclusive_file_lock(lock_path) as metadata:
        current = _read_lock_metadata(lock_path)
        assert current is not None
        assert current.pid == os.getpid()
        assert current.process_start_time == metadata.process_start_time

    assert not metadata_path.exists()


def test_exclusive_file_lock_times_out_with_live_holder(tmp_path):
    lock_path = tmp_path / "boot.lock"
    repo_root = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [repo_root, env.get("PYTHONPATH", "")]))

    script = "\n".join(
        [
            "import sys",
            "import time",
            "sys.path.insert(0, sys.argv[2])",
            "from dotscope.storage.file_lock import exclusive_file_lock",
            "with exclusive_file_lock(sys.argv[1], timeout_seconds=5):",
            "    print('ready', flush=True)",
            "    time.sleep(2)",
        ]
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path), repo_root],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        if line != "ready":
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise AssertionError(f"expected ready signal, got {line!r}; stderr={stderr!r}")
        with pytest.raises(FileLockTimeoutError):
            with exclusive_file_lock(lock_path, timeout_seconds=0.2, poll_interval=0.05):
                pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_read_text_with_retry_handles_transient_sharing_error(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{}", encoding="utf-8")

    original = Path.read_text
    state = {"calls": 0}

    def flaky_read(self: Path, *args, **kwargs):
        if self == target and state["calls"] == 0:
            state["calls"] += 1
            error = PermissionError(13, "sharing violation")
            error.winerror = 32
            raise error
        return original(self, *args, **kwargs)

    monkeypatch.setattr("dotscope.storage.atomic._is_transient_read_error", lambda exc: True)
    monkeypatch.setattr(Path, "read_text", flaky_read)

    assert read_text_with_retry(target) == "{}"
