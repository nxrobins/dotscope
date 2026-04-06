"""Tests for token budgeting."""

import os
import pytest
from dotscope.passes.budget_allocator import apply_budget
from dotscope.passes.budget_allocator import _rank_files
from dotscope.models import ResolvedScope


class TestBudget:
    def test_no_truncation_when_under_budget(self):
        resolved = ResolvedScope(
            files=[],
            context="Short context",
            token_estimate=10,
            scope_chain=["test"],
        )
        result = apply_budget(resolved, max_tokens=10000)
        assert not result.truncated

    def test_truncation_when_over_budget(self, tmp_path):
        # Create some files
        files = []
        for i in range(10):
            f = tmp_path / f"file{i}.py"
            f.write_text("x" * 1000)  # ~250 tokens each
            files.append(str(f))

        resolved = ResolvedScope(
            files=files,
            context="Context",
            token_estimate=2500,
            scope_chain=["test"],
        )

        result = apply_budget(resolved, max_tokens=500)
        assert result.truncated
        assert len(result.files) < len(files)

    def test_context_always_included(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("x" * 4000)

        resolved = ResolvedScope(
            files=[str(f)],
            context="Important context",
            token_estimate=1000,
            scope_chain=["test"],
        )

        result = apply_budget(resolved, max_tokens=100)
        assert "Important context" in result.context

    def test_zero_budget(self):
        resolved = ResolvedScope(
            files=["/some/file.py"],
            context="Context",
            token_estimate=100,
            scope_chain=["test"],
        )
        result = apply_budget(resolved, max_tokens=0)
        assert result.truncated
        assert len(result.files) == 0


class TestRankFilesTaskAwareness:
    def test_directory_name_boosts_score(self, tmp_path):
        """File in matching directory ranks above file in non-matching dir."""
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        api_dir = tmp_path / "api"
        api_dir.mkdir()

        storage_file = storage_dir / "cache.py"
        storage_file.write_text("# cache logic\n")
        api_file = api_dir / "routes.py"
        api_file.write_text("# api routes\n")

        ranked = _rank_files(
            [str(storage_file), str(api_file)],
            task="Fix storage caching bug",
        )

        scores = {os.path.basename(p): s for p, s in ranked}
        assert scores["cache.py"] > scores["routes.py"]

    def test_full_path_matching(self, tmp_path):
        """Task words match directory names, not just filenames."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        utils_dir = tmp_path / "utils"
        utils_dir.mkdir()

        model_file = models_dir / "base.py"
        model_file.write_text("# base model\n")
        util_file = utils_dir / "base.py"
        util_file.write_text("# base util\n")

        ranked = _rank_files(
            [str(model_file), str(util_file)],
            task="Update models validation",
        )

        # model_file should rank higher because 'models' dir matches task
        paths = [p for p, _ in ranked]
        assert str(model_file) == paths[0]

    def test_zero_overlap_penalized(self, tmp_path):
        """Files with no path overlap get demoted."""
        relevant = tmp_path / "auth" / "handler.py"
        relevant.parent.mkdir(parents=True)
        relevant.write_text("# auth\n")

        irrelevant = tmp_path / "config" / "settings.py"
        irrelevant.parent.mkdir(parents=True)
        irrelevant.write_text("# config\n")

        ranked = _rank_files(
            [str(relevant), str(irrelevant)],
            task="Fix auth handler",
        )

        scores = {os.path.basename(p): s for p, s in ranked}
        assert scores["handler.py"] > scores["settings.py"]
