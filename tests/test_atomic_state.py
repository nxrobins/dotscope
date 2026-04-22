"""Tests for atomic machine-state persistence helpers."""

import json

import pytest

from dotscope.storage.atomic import atomic_write_json


class TestAtomicWriteJson:
    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "state.json"

        atomic_write_json(path, {"status": "ok"})

        assert json.loads(path.read_text(encoding="utf-8")) == {"status": "ok"}

    def test_preserves_existing_contents_on_replace_failure(self, tmp_path, monkeypatch):
        path = tmp_path / "state.json"
        path.write_text('{"value": 1}', encoding="utf-8")

        def fail_replace(_src, _dst):
            raise OSError("disk full")

        monkeypatch.setattr("dotscope.storage.atomic.os.replace", fail_replace)

        with pytest.raises(OSError):
            atomic_write_json(path, {"value": 2})

        assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}
        assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
