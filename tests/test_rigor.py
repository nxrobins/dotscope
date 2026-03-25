"""Tests for compiler rigor: assertions, regressions, bench, debug."""

import hashlib
import os
import tempfile

import pytest

from dotscope.assertions import (
    Assertion, ContextExhaustionError, check_output_assertions,
    get_required_files,
)
from dotscope.budget import _boost_required
from dotscope.timing import record_timing, load_timings, median, percentile
from dotscope.regression import (
    RegressionCase, ReplayResult, maybe_freeze_session,
    load_regressions, format_replay_report,
)
from dotscope.debug import (
    BisectionResult, format_debug_report, _diagnose, _parse_sections,
)
from dotscope.bench import BenchReport, format_bench_report


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class TestAssertions:
    def test_get_required_files(self):
        assertions = [
            Assertion(scope="auth", ensure_includes=["models/user.py"]),
            Assertion(scope="*", ensure_includes=["config.py"]),
        ]
        required = get_required_files(assertions, "auth")
        assert "models/user.py" in required
        assert "config.py" in required

    def test_wildcard_scope(self):
        assertions = [Assertion(scope="*", ensure_includes=["global.py"])]
        required = get_required_files(assertions, "anything")
        assert "global.py" in required

    def test_non_matching_scope_excluded(self):
        assertions = [Assertion(scope="payments", ensure_includes=["billing.py"])]
        required = get_required_files(assertions, "auth")
        assert "billing.py" not in required

    def test_ensure_context_contains_passes(self):
        assertions = [Assertion(scope="auth", ensure_context_contains=["soft deletes"])]
        err = check_output_assertions(
            "User model has soft deletes", [], assertions, "auth"
        )
        assert err is None

    def test_ensure_context_contains_fails(self):
        assertions = [Assertion(
            scope="auth",
            ensure_context_contains=["idempotency"],
            reason="Payment webhooks need idempotency",
        )]
        err = check_output_assertions("No relevant info", [], assertions, "auth")
        assert err is not None
        assert err.assertion_type == "ensure_context_contains"

    def test_ensure_constraints_passes(self):
        assertions = [Assertion(scope="*", ensure_constraints=True)]
        err = check_output_assertions("ctx", [{"message": "x"}], assertions, "auth")
        assert err is None

    def test_ensure_constraints_fails(self):
        assertions = [Assertion(scope="*", ensure_constraints=True, reason="Need rules")]
        err = check_output_assertions("ctx", [], assertions, "auth")
        assert err is not None
        assert err.assertion_type == "ensure_constraints"

    def test_context_exhaustion_error_to_dict(self):
        err = ContextExhaustionError(
            assertion_type="ensure_includes",
            detail="Cannot fit models/user.py",
            file="models/user.py",
            file_tokens=1200,
            budget=4000,
        )
        d = err.to_dict()
        assert d["error"] == "context_exhaustion"
        assert d["assertion_failed"]["file"] == "models/user.py"


class TestBudgetBoost:
    def test_boost_required(self):
        scored = [("a.py", 0.5), ("b.py", 0.8), ("c.py", 0.3)]
        boosted = _boost_required(scored, {"a.py"})
        assert boosted[0][0] == "a.py"
        assert boosted[0][1] == float("inf")


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

class TestTiming:
    def test_record_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".dotscope"))
            record_timing(tmp, "resolve", 12.5)
            record_timing(tmp, "check", 28.3)
            entries = load_timings(tmp)
            assert len(entries) == 2
            assert entries[0].operation == "resolve"

    def test_median(self):
        assert median([1, 2, 3, 4, 5]) == 3
        assert median([1, 2, 3, 4]) == 2.5
        assert median([]) == 0.0

    def test_percentile(self):
        values = list(range(100))
        assert percentile(values, 95) == 95


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

class TestRegression:
    def test_freeze_successful(self):
        class FakeObs:
            recall = 0.9
            timestamp = "2026-03-25"

        class FakeSess:
            predicted_files = ["a.py", "b.py"]
            context_hash = "abc123"
            scope_expr = "auth"

        with tempfile.TemporaryDirectory() as tmp:
            case_id = maybe_freeze_session(FakeObs(), FakeSess(), tmp)
            assert case_id is not None
            cases = load_regressions(tmp)
            assert len(cases) == 1

    def test_skip_low_recall(self):
        class FakeObs:
            recall = 0.3

        class FakeSess:
            pass

        with tempfile.TemporaryDirectory() as tmp:
            assert maybe_freeze_session(FakeObs(), FakeSess(), tmp) is None

    def test_format_replay_report(self):
        case = RegressionCase(id="reg_abc", scope_expr="auth")
        case.expected_files = ["a.py"]
        result = ReplayResult(
            case=case, new_files=["a.py"],
            files_dropped=[], files_added=[],
        )
        output = format_replay_report([result])
        assert "1/1 passed" in output


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

class TestDebug:
    def test_diagnose_resolution_gap(self):
        diagnosis, recs = _diagnose(["missing.py"], [], [])
        assert diagnosis == "resolution_gap"
        assert any("missing.py" in r for r in recs)

    def test_diagnose_agent_ignored(self):
        diagnosis, recs = _diagnose([], [{"message": "x"}], [])
        assert diagnosis == "agent_ignored"

    def test_diagnose_constraint_gap(self):
        diagnosis, recs = _diagnose([], [], [])
        assert diagnosis == "constraint_gap"

    def test_parse_sections(self):
        context = "intro\n## Contracts\ncontract info\n## Stability\nstable"
        sections = _parse_sections(context)
        assert "Contracts" in sections
        assert "Stability" in sections

    def test_format_debug_report(self):
        result = BisectionResult(
            session_id="abc123",
            missing_files=["cache/sessions.py"],
            diagnosis="resolution_gap",
            recommendations=["Add cache/sessions.py"],
        )
        output = format_debug_report(result)
        assert "resolution_gap" in output
        assert "cache/sessions.py" in output


# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------

class TestBench:
    def test_format_bench_report(self):
        report = BenchReport(
            avg_tokens_resolved=100,
            avg_tokens_used=73,
            efficiency_ratio=0.73,
            total_commits=47,
            resolve_median_ms=12.0,
            resolve_p95_ms=34.0,
            total_scopes=12,
            scopes_above_80_recall=9,
        )
        output = format_bench_report(report)
        assert "Token Efficiency" in output
        assert "73" in output

    def test_empty_report(self):
        report = BenchReport()
        output = format_bench_report(report)
        assert "No observation data" in output
