"""Tests for .dotscopeignore pattern matching."""

import os
import tempfile

from dotscope.ignore import load_ignore_patterns, should_skip
from dotscope.constants import SKIP_DIRS


class TestLoadIgnorePatterns:
    def test_no_file(self, tmp_path):
        assert load_ignore_patterns(str(tmp_path)) == []

    def test_empty_file(self, tmp_path):
        (tmp_path / ".dotscopeignore").write_text("")
        assert load_ignore_patterns(str(tmp_path)) == []

    def test_comments_skipped(self, tmp_path):
        (tmp_path / ".dotscopeignore").write_text("# comment\n\n# another\n")
        assert load_ignore_patterns(str(tmp_path)) == []

    def test_patterns_loaded(self, tmp_path):
        (tmp_path / ".dotscopeignore").write_text(
            "renderer/target/\n*.fbx\n# comment\nassets/raw/\n"
        )
        patterns = load_ignore_patterns(str(tmp_path))
        assert patterns == ["renderer/target/", "*.fbx", "assets/raw/"]


class TestShouldSkip:
    def test_skip_dirs_match(self):
        assert should_skip("node_modules/foo.js", SKIP_DIRS, [])
        assert should_skip("src/node_modules/bar.js", SKIP_DIRS, [])

    def test_skip_dirs_no_match(self):
        assert not should_skip("src/handler.py", SKIP_DIRS, [])

    def test_glob_pattern(self):
        assert should_skip("model.fbx", frozenset(), ["*.fbx"])
        assert should_skip("assets/scene.fbx", frozenset(), ["*.fbx"])
        assert not should_skip("handler.py", frozenset(), ["*.fbx"])

    def test_directory_pattern(self):
        patterns = ["renderer/target/"]
        assert should_skip("renderer/target/debug/main.rs", frozenset(), patterns)
        assert not should_skip("renderer/src/main.rs", frozenset(), patterns)

    def test_combined(self):
        patterns = ["*.wav", "build_output/"]
        assert should_skip("node_modules/pkg.js", SKIP_DIRS, patterns)
        assert should_skip("audio/effect.wav", SKIP_DIRS, patterns)
        assert should_skip("build_output/release/app", SKIP_DIRS, patterns)
        assert not should_skip("src/main.py", SKIP_DIRS, patterns)

    def test_new_skip_dirs(self):
        """Verify the expanded SKIP_DIRS covers common build dirs."""
        assert should_skip("target/debug/main", SKIP_DIRS, [])
        assert should_skip("src/target/release/bin", SKIP_DIRS, [])
        assert should_skip(".next/cache/foo", SKIP_DIRS, [])
        assert should_skip(".dotscope/sessions/abc.json", SKIP_DIRS, [])
        assert should_skip(".claude/settings.json", SKIP_DIRS, [])
        assert should_skip("out/compiled.js", SKIP_DIRS, [])
        assert should_skip("obj/Debug/net6.0/app.dll", SKIP_DIRS, [])
        assert should_skip("coverage/lcov.info", SKIP_DIRS, [])
