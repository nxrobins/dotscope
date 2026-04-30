"""Tests for `dotscope cut-score`. No live network: all GitHub responses
are canned via a fake httpx-shaped client."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from dotscope.cut_score import (
    CUT_SCORE_VERSION,
    CutScoreError,
    LOC_HARD_GATE,
    LOC_SOFT_GATE,
    MODULE_EXTRACTORS,
    QUALIFYING_RATE_GATE,
    RECOMMENDED_MODULE_STYLE,
    aggregate_repo,
    candidate_test_paths,
    count_modules,
    is_test_path,
    loc_proxy,
    parse_label_overrides,
    parse_module_style_overrides,
    regression_test_classification,
    resolve_module_style,
    run_cut_score,
    score_pr,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestPathClassification:
    @pytest.mark.parametrize("path", [
        "tests/test_foo.py",
        "testing/test_bar.py",
        "src/_pytest/foo/test_thing.py",
        "lib/sqlalchemy/orm/foo_test.py",
        "deep/nested/test_x.py",
    ])
    def test_is_test_path_positive(self, path):
        assert is_test_path(path) is True

    @pytest.mark.parametrize("path", [
        "src/_pytest/foo.py",
        "lib/sqlalchemy/orm/util.py",
        "pydantic/validators.py",
        "README.md",
    ])
    def test_is_test_path_negative(self, path):
        assert is_test_path(path) is False


class TestRegressionTestClassification:
    def test_modified_takes_precedence_over_added(self):
        files = [
            {"filename": "tests/test_one.py", "status": "modified"},
            {"filename": "tests/test_two.py", "status": "added"},
        ]
        assert regression_test_classification(files) == "modified"

    def test_only_added_test(self):
        files = [
            {"filename": "src/foo.py", "status": "modified"},
            {"filename": "tests/test_new.py", "status": "added"},
        ]
        assert regression_test_classification(files) == "added"

    def test_no_test_at_all(self):
        files = [{"filename": "src/foo.py", "status": "modified"}]
        assert regression_test_classification(files) == "absent"

    def test_renamed_counts_as_modified(self):
        files = [
            {"filename": "tests/test_foo.py", "status": "renamed"},
            {"filename": "src/foo.py", "status": "modified"},
        ]
        assert regression_test_classification(files) == "modified"

    def test_candidate_paths_filter_to_modified_status(self):
        files = [
            {"filename": "tests/test_old.py", "status": "modified"},
            {"filename": "tests/test_new.py", "status": "added"},
        ]
        assert candidate_test_paths(files, "modified") == ["tests/test_old.py"]

    def test_candidate_paths_for_added_status(self):
        files = [
            {"filename": "tests/test_old.py", "status": "modified"},
            {"filename": "tests/test_new.py", "status": "added"},
        ]
        assert candidate_test_paths(files, "added") == ["tests/test_new.py"]


class TestModuleExtractors:
    @pytest.mark.parametrize("style,path,expected", [
        ("top-pkg", "lib/sqlalchemy/orm/foo.py", "lib"),
        ("depth-2", "lib/sqlalchemy/orm/foo.py", "sqlalchemy"),
        ("depth-3", "lib/sqlalchemy/orm/foo.py", "orm"),
        ("leaf-dir", "lib/sqlalchemy/orm/foo.py", "orm"),
        ("top-pkg", "pydantic/validators.py", "pydantic"),
        ("depth-2", "pydantic/validators.py", "pydantic"),  # falls back to closest dir
        ("leaf-dir", "pydantic/validators.py", "pydantic"),
        ("depth-2", "src/_pytest/foo.py", "_pytest"),
        ("top-pkg", "README.md", "README.md"),
    ])
    def test_extractor(self, style, path, expected):
        extractor = MODULE_EXTRACTORS[style]
        assert extractor(path) == expected

    def test_count_modules_dedupes_in_order(self):
        files = [
            {"filename": "lib/sqlalchemy/orm/a.py"},
            {"filename": "lib/sqlalchemy/sql/b.py"},
            {"filename": "lib/sqlalchemy/orm/c.py"},
        ]
        modules = count_modules(files, MODULE_EXTRACTORS["depth-3"])
        assert modules == ["orm", "sql"]


class TestLocProxy:
    def test_sums_additions_and_deletions(self):
        files = [
            {"additions": 10, "deletions": 3},
            {"additions": 5, "deletions": 0},
        ]
        assert loc_proxy(files) == 18

    def test_handles_missing_keys(self):
        files = [{"additions": 7}, {"deletions": 4}, {}]
        assert loc_proxy(files) == 11


# ---------------------------------------------------------------------------
# score_pr / aggregate_repo
# ---------------------------------------------------------------------------

def _make_files(specs):
    """`specs` is list of (filename, status, additions, deletions)."""
    return [
        {"filename": fn, "status": st, "additions": a, "deletions": d}
        for fn, st, a, d in specs
    ]


def _make_pr(number=1, title="fix bug", closed_at="2026-01-01T00:00:00Z"):
    return {"number": number, "title": title, "closed_at": closed_at}


class TestScorePr:
    def test_qualifying_public_modified_test(self):
        pr = _make_pr()
        files = _make_files([
            ("lib/sqlalchemy/orm/a.py", "modified", 5, 1),
            ("lib/sqlalchemy/sql/b.py", "modified", 4, 0),
            ("test/orm/test_a.py", "modified", 3, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["depth-3"], "sqlalchemy/sqlalchemy")
        assert row.qualifies_public is True
        assert row.qualifies_diagnostic is True
        assert row.regression_test_status == "modified"
        assert row.candidate_test_paths == ["test/orm/test_a.py"]
        assert row.reasons == []

    def test_added_test_excluded_from_public_only(self):
        pr = _make_pr()
        files = _make_files([
            ("lib/sqlalchemy/orm/a.py", "modified", 5, 1),
            ("lib/sqlalchemy/sql/b.py", "modified", 4, 0),
            ("test/orm/test_new.py", "added", 30, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["depth-3"], "sqlalchemy/sqlalchemy")
        assert row.qualifies_public is False
        assert row.qualifies_diagnostic is True
        assert row.regression_test_status == "added"
        assert any("Deviation 1" in r for r in row.reasons)

    def test_too_few_files_fails(self):
        pr = _make_pr()
        files = _make_files([
            ("a.py", "modified", 1, 0),
            ("test_a.py", "modified", 1, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["top-pkg"], "x/y")
        assert row.qualifies_public is False
        assert row.qualifies_diagnostic is False
        assert any("files_changed" in r for r in row.reasons)

    def test_too_few_modules_fails(self):
        pr = _make_pr()
        # all files in same top-level package
        files = _make_files([
            ("pkg/a.py", "modified", 5, 0),
            ("pkg/b.py", "modified", 5, 0),
            ("pkg/test_a.py", "modified", 3, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["top-pkg"], "x/y")
        assert row.qualifies_public is False
        assert any("modules" in r for r in row.reasons)

    def test_no_regression_test_fails(self):
        pr = _make_pr()
        files = _make_files([
            ("pkg_a/x.py", "modified", 5, 0),
            ("pkg_b/y.py", "modified", 5, 0),
            ("pkg_b/z.py", "modified", 5, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["top-pkg"], "x/y")
        assert row.qualifies_public is False
        assert any("no regression test" in r for r in row.reasons)

    def test_loc_hard_gate_fails(self):
        pr = _make_pr()
        files = _make_files([
            ("pkg_a/x.py", "modified", LOC_HARD_GATE, 5),
            ("pkg_b/y.py", "modified", 1, 0),
            ("tests/test_a.py", "modified", 1, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["top-pkg"], "x/y")
        assert row.qualifies_public is False
        assert any("hard gate" in r for r in row.reasons)

    def test_loc_soft_band_yields_none(self):
        pr = _make_pr()
        soft_loc = LOC_SOFT_GATE + 50  # in soft band
        files = _make_files([
            ("pkg_a/x.py", "modified", soft_loc, 0),
            ("pkg_b/y.py", "modified", 1, 0),
            ("tests/test_a.py", "modified", 1, 0),
        ])
        row = score_pr(pr, files, MODULE_EXTRACTORS["top-pkg"], "x/y")
        assert row.qualifies_public is None
        assert row.qualifies_diagnostic is None
        assert row.proxies["in_loc_soft_band"] is True


class TestAggregateRepo:
    def test_gate_passes_at_60_percent(self):
        rows = []
        for i in range(7):  # 7 / 10 = 70% public
            row_files = _make_files([
                ("a/x.py", "modified", 1, 0),
                ("b/y.py", "modified", 1, 0),
                ("tests/test_a.py", "modified", 1, 0),
            ])
            rows.append(score_pr(_make_pr(i), row_files, MODULE_EXTRACTORS["top-pkg"], "x/y"))
        for i in range(3):
            row_files = _make_files([("a/x.py", "modified", 1, 0)])
            rows.append(score_pr(_make_pr(i + 100), row_files, MODULE_EXTRACTORS["top-pkg"], "x/y"))

        summary = aggregate_repo(rows, "x/y")
        assert summary["gate_passed"] is True
        assert summary["qualifying_rate_public"] >= QUALIFYING_RATE_GATE
        assert summary["fallback_recommendation"] is None

    def test_gate_fails_with_fallback_recommendation(self):
        rows = []
        for i in range(5):  # only 5 / 10 = 50%
            row_files = _make_files([
                ("a/x.py", "modified", 1, 0),
                ("b/y.py", "modified", 1, 0),
                ("tests/test_a.py", "modified", 1, 0),
            ])
            rows.append(score_pr(_make_pr(i), row_files, MODULE_EXTRACTORS["top-pkg"], "x/y"))
        for i in range(5):
            row_files = _make_files([("a/x.py", "modified", 1, 0)])
            rows.append(score_pr(_make_pr(i + 100), row_files, MODULE_EXTRACTORS["top-pkg"], "x/y"))

        summary = aggregate_repo(rows, "x/y")
        assert summary["gate_passed"] is False
        assert "Django" in summary["fallback_recommendation"]
        assert "Celery" in summary["fallback_recommendation"]


# ---------------------------------------------------------------------------
# Override parsing & resolution
# ---------------------------------------------------------------------------

class TestOverrides:
    def test_parse_label_overrides(self):
        result = parse_label_overrides([
            "pytest-dev/pytest=type: bug",
            "pydantic/pydantic=bug V2",
        ])
        assert result == {
            "pytest-dev/pytest": "type: bug",
            "pydantic/pydantic": "bug V2",
        }

    def test_parse_label_overrides_rejects_bad_input(self):
        with pytest.raises(CutScoreError):
            parse_label_overrides(["malformed"])
        with pytest.raises(CutScoreError):
            parse_label_overrides(["repo="])
        with pytest.raises(CutScoreError):
            parse_label_overrides(["=label"])

    def test_parse_module_style_override(self):
        result = parse_module_style_overrides(["x/y=depth-3"])
        assert result == {"x/y": "depth-3"}

    def test_parse_module_style_override_rejects_unknown_style(self):
        with pytest.raises(CutScoreError):
            parse_module_style_overrides(["x/y=banana"])

    def test_resolve_module_style_override_wins(self):
        assert resolve_module_style(
            "sqlalchemy/sqlalchemy", "top-pkg", {"sqlalchemy/sqlalchemy": "leaf-dir"}
        ) == "leaf-dir"

    def test_resolve_module_style_recommended_over_default(self):
        # SQLAlchemy has a recommended of depth-3
        assert RECOMMENDED_MODULE_STYLE["sqlalchemy/sqlalchemy"] == "depth-3"
        assert resolve_module_style(
            "sqlalchemy/sqlalchemy", "top-pkg", {}
        ) == "depth-3"

    def test_resolve_module_style_falls_back_to_default(self):
        assert resolve_module_style("unknown/repo", "depth-2", {}) == "depth-2"


# ---------------------------------------------------------------------------
# End-to-end with fake httpx client
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, payload: Any, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


class FakeClient:
    """Minimal httpx-shaped client returning canned responses keyed by path."""

    def __init__(self, responses: Dict[str, List[_FakeResponse]]):
        # responses: path -> list of responses (FIFO per call)
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: List[tuple] = []

    def get(self, path: str, params: Optional[Dict[str, Any]] = None):
        self.calls.append((path, params))
        queue = self._responses.get(path)
        if not queue:
            raise AssertionError(f"unexpected GET {path} params={params}")
        return queue.pop(0)

    def close(self):
        pass


class TestEndToEnd:
    def test_run_cut_score_with_canned_responses(self):
        # One repo, two PRs: one qualifies_public, one doesn't (no test).
        search_payload_p1 = {
            "items": [
                {
                    "number": 101,
                    "title": "fix orm bug",
                    "closed_at": "2026-04-01T00:00:00Z",
                },
                {
                    "number": 102,
                    "title": "fix sql bug",
                    "closed_at": "2026-04-02T00:00:00Z",
                },
            ]
        }
        search_payload_p2 = {"items": []}
        files_101 = [
            {"filename": "lib/sqlalchemy/orm/a.py", "status": "modified",
             "additions": 5, "deletions": 0},
            {"filename": "lib/sqlalchemy/sql/b.py", "status": "modified",
             "additions": 5, "deletions": 0},
            {"filename": "test/orm/test_a.py", "status": "modified",
             "additions": 5, "deletions": 0},
        ]
        files_102 = [
            {"filename": "lib/sqlalchemy/orm/c.py", "status": "modified",
             "additions": 5, "deletions": 0},
            {"filename": "lib/sqlalchemy/sql/d.py", "status": "modified",
             "additions": 5, "deletions": 0},
            {"filename": "lib/sqlalchemy/orm/e.py", "status": "modified",
             "additions": 5, "deletions": 0},
        ]
        client = FakeClient({
            "/search/issues": [
                _FakeResponse(200, search_payload_p1),
                _FakeResponse(200, search_payload_p2),
            ],
            "/repos/sqlalchemy/sqlalchemy/pulls/101/files": [
                _FakeResponse(200, files_101),
            ],
            "/repos/sqlalchemy/sqlalchemy/pulls/102/files": [
                _FakeResponse(200, files_102),
            ],
        })

        payload = run_cut_score(
            repos=["sqlalchemy/sqlalchemy"],
            n=2,
            token=None,
            label_overrides={},
            default_module_style="top-pkg",
            module_style_overrides={},
            client=client,
        )

        assert payload["cut_score_version"] == CUT_SCORE_VERSION
        assert len(payload["repos"]) == 1
        entry = payload["repos"][0]
        # SQLAlchemy gets depth-3 from the recommended map even though
        # default is top-pkg
        assert entry["module_style_used"] == "depth-3"
        assert entry["module_style_source"] == "recommended"
        rows = entry["rows"]
        assert len(rows) == 2
        # PR 101 qualifies (orm + sql + test); PR 102 does not (no test, no module diversity wrt depth-3 -> orm,sql,orm = 2 modules)
        by_pr = {r["pr"]: r for r in rows}
        assert by_pr[101]["qualifies_public"] is True
        assert by_pr[102]["qualifies_public"] is False
        assert "no regression test" in " ".join(by_pr[102]["reasons"])

    def test_run_cut_score_writes_out_file(self, tmp_path):
        client = FakeClient({
            "/search/issues": [_FakeResponse(200, {"items": []})],
        })
        out = tmp_path / "cut_score.json"
        payload = run_cut_score(
            repos=["x/y"],
            n=5,
            token=None,
            label_overrides={},
            default_module_style="top-pkg",
            module_style_overrides={},
            client=client,
        )
        from dotscope.cut_score import write_report
        write_report(payload, str(out))
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["cut_score_version"] == CUT_SCORE_VERSION
