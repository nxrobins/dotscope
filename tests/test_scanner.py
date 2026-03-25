"""Tests for auto-scanner."""

import os
import pytest
from dotscope.scanner import scan_directory


class TestScanner:
    def test_scan_python_project(self, tmp_path):
        src = tmp_path / "myapp"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("print('hello')\n")
        (src / "utils.py").write_text("def helper(): pass\n")

        tests = src / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("def test_main(): pass\n")

        config = scan_directory(str(src))

        assert "myapp" in config.description
        assert "Python" in config.description
        assert any("myapp/" in inc for inc in config.includes)
        assert config.tokens_estimate > 0

    def test_scan_detects_excludes(self, tmp_path):
        src = tmp_path / "app"
        src.mkdir()
        (src / "main.py").write_text("")

        migrations = src / "migrations"
        migrations.mkdir()
        (migrations / "001_init.py").write_text("")

        config = scan_directory(str(src))
        assert any("migrations" in exc for exc in config.excludes)

    def test_scan_tags_inferred(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "login.py").write_text("")

        config = scan_directory(str(auth))
        assert "auth" in config.tags
        assert "authentication" in config.tags

    def test_scan_context_has_todo(self, tmp_path):
        src = tmp_path / "lib"
        src.mkdir()
        (src / "module.py").write_text("")

        config = scan_directory(str(src))
        assert "TODO" in config.context_str
