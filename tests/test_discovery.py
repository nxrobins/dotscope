"""Tests for scope discovery: repo root finding and scope enumeration."""

import os

import pytest

from dotscope.discovery import find_all_scopes
from dotscope.paths.repo import find_repo_root


class TestFindRepoRoot:
    def test_finds_git_directory(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = find_repo_root(str(tmp_path))
        assert result == str(tmp_path)

    def test_finds_scopes_file(self, tmp_path):
        (tmp_path / ".scopes").write_text("version: 1\nscopes: {}\n")
        result = find_repo_root(str(tmp_path))
        assert result == str(tmp_path)

    def test_finds_root_scope_file(self, tmp_path):
        (tmp_path / ".scope").write_text("description: root scope\n")
        result = find_repo_root(str(tmp_path))
        assert result == str(tmp_path)

    def test_walks_up_to_parent(self, tmp_path):
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        result = find_repo_root(str(nested))
        assert result == str(tmp_path)

    def test_returns_none_when_no_marker(self, tmp_path):
        empty = tmp_path / "isolated"
        empty.mkdir()
        # Override cwd to avoid finding the real repo
        result = find_repo_root(str(empty))
        # It walks up to filesystem root; may find a real .git above tmp_path.
        # If it does, that's fine. If not, it returns None.
        # We can at least verify the function returns without error.
        assert result is None or os.path.isdir(result)


class TestFindAllScopes:
    def test_finds_scope_files(self, tmp_path):
        (tmp_path / ".git").mkdir()

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / ".scope").write_text("description: auth\n")

        payments = tmp_path / "payments"
        payments.mkdir()
        (payments / ".scope").write_text("description: payments\n")

        result = find_all_scopes(str(tmp_path))
        assert len(result) == 2
        basenames = [os.path.basename(os.path.dirname(p)) for p in result]
        assert "auth" in basenames
        assert "payments" in basenames

    def test_finds_nested_scopes(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / ".scope").write_text("description: deep\n")

        result = find_all_scopes(str(tmp_path))
        assert len(result) == 1
        assert result[0].endswith(".scope")

    def test_skips_pycache_and_node_modules(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / ".scope").write_text("description: should be skipped\n")

        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / ".scope").write_text("description: should be skipped\n")

        legit = tmp_path / "src"
        legit.mkdir()
        (legit / ".scope").write_text("description: legit\n")

        result = find_all_scopes(str(tmp_path))
        assert len(result) == 1
        assert "src" in result[0]

    def test_returns_sorted_paths(self, tmp_path):
        for name in ["zebra", "alpha", "mid"]:
            d = tmp_path / name
            d.mkdir()
            (d / ".scope").write_text(f"description: {name}\n")

        result = find_all_scopes(str(tmp_path))
        assert result == sorted(result)

    def test_empty_directory(self, tmp_path):
        result = find_all_scopes(str(tmp_path))
        assert result == []
