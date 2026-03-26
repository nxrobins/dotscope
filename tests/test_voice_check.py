"""Tests for voice sentinel check: bare excepts + type hints."""

import os
import tempfile

from dotscope.passes.sentinel.checks.voice import check_voice
from dotscope.models.intent import Severity, CheckCategory


class TestBareExcepts:
    def test_hold_on_bare_except(self):
        src = "try:\n    pass\nexcept:\n    pass\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.py")
            with open(path, "w") as f:
                f.write(src)
            results = check_voice(
                ["bad.py"], {"bad.py": ["    pass"]},
                {"enforce": {"bare_excepts": "hold"}}, d,
            )
            assert len(results) == 1
            assert results[0].severity == Severity.HOLD
            assert results[0].category == CheckCategory.VOICE

    def test_note_on_bare_except(self):
        src = "try:\n    pass\nexcept:\n    pass\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.py")
            with open(path, "w") as f:
                f.write(src)
            results = check_voice(
                ["bad.py"], {"bad.py": []},
                {"enforce": {"bare_excepts": "note"}}, d,
            )
            assert len(results) == 1
            assert results[0].severity == Severity.NOTE

    def test_no_check_when_disabled(self):
        src = "try:\n    pass\nexcept:\n    pass\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.py")
            with open(path, "w") as f:
                f.write(src)
            results = check_voice(
                ["bad.py"], {"bad.py": []},
                {"enforce": {"bare_excepts": False}}, d,
            )
            assert len(results) == 0

    def test_specific_except_passes(self):
        src = "try:\n    pass\nexcept ValueError:\n    pass\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ok.py")
            with open(path, "w") as f:
                f.write(src)
            results = check_voice(
                ["ok.py"], {"ok.py": []},
                {"enforce": {"bare_excepts": "hold"}}, d,
            )
            assert len(results) == 0


class TestMissingTypeHints:
    def test_fires_on_new_untyped_function(self):
        src = "def process(data):\n    return data\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mod.py")
            with open(path, "w") as f:
                f.write(src)
            results = check_voice(
                ["mod.py"],
                {"mod.py": ["def process(data):"]},
                {"enforce": {"missing_type_hints": "note"}}, d,
            )
            assert len(results) == 1
            assert "process" in results[0].message

    def test_skips_existing_function(self):
        src = "def process(data):\n    return data\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mod.py")
            with open(path, "w") as f:
                f.write(src)
            # Function not in added_lines = existing
            results = check_voice(
                ["mod.py"],
                {"mod.py": ["    return data"]},
                {"enforce": {"missing_type_hints": "note"}}, d,
            )
            assert len(results) == 0

    def test_typed_function_passes(self):
        src = "def process(data: str) -> str:\n    return data\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mod.py")
            with open(path, "w") as f:
                f.write(src)
            results = check_voice(
                ["mod.py"],
                {"mod.py": ["def process(data: str) -> str:"]},
                {"enforce": {"missing_type_hints": "note"}}, d,
            )
            assert len(results) == 0

    def test_no_config_returns_empty(self):
        results = check_voice(["a.py"], {}, None, "/tmp")
        assert results == []

    def test_empty_enforce_returns_empty(self):
        results = check_voice(["a.py"], {}, {"enforce": {}}, "/tmp")
        assert results == []
