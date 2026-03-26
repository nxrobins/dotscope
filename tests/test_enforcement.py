"""Tests for the architectural enforcement system."""

import json
import os
import tempfile

import pytest

from dotscope.check.models import (
    CheckCategory, CheckReport, CheckResult, Constraint,
    IntentDirective, ProposedFix, Severity,
)
from dotscope.check.checks.boundary import check_boundaries
from dotscope.check.checks.contracts import check_contracts, _ack_id
from dotscope.check.checks.antipattern import check_antipatterns
from dotscope.check.checks.stability import check_stability
from dotscope.check.checks.direction import check_dependency_direction
from dotscope.check.checks.intent import check_intent_holds, check_intent_notes
from dotscope.check.acknowledge import (
    record_acknowledgment, load_acknowledgments, compute_decayed_confidence,
)
from dotscope.check.constraints import build_constraints
from dotscope.check.checker import check_diff, format_terminal, _parse_diff


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestModels:
    def test_check_report_three_tiers(self):
        r = CheckReport(
            passed=False,
            results=[
                CheckResult(passed=False, category=CheckCategory.INTENT,
                            severity=Severity.GUARD, message="frozen"),
                CheckResult(passed=False, category=CheckCategory.CONTRACT,
                            severity=Severity.NUDGE, message="coupled"),
                CheckResult(passed=False, category=CheckCategory.STABILITY,
                            severity=Severity.NOTE, message="stable"),
            ],
        )
        assert len(r.guards) == 1
        assert len(r.nudges) == 1
        assert len(r.notes) == 1
        assert len(r.holds) == 1  # backwards compat alias for guards

    def test_nudges_do_not_block(self):
        r = CheckReport(
            passed=True,
            results=[
                CheckResult(passed=False, category=CheckCategory.CONTRACT,
                            severity=Severity.NUDGE, message="x"),
            ],
        )
        # NUDGE does not make passed=False (only GUARD does)
        assert r.guards == []
        assert len(r.nudges) == 1

    def test_check_report_empty(self):
        r = CheckReport(passed=True)
        assert r.guards == []
        assert r.nudges == []
        assert r.notes == []


# ---------------------------------------------------------------------------
# Boundary check
# ---------------------------------------------------------------------------

class TestBoundaryCheck:
    def test_file_in_resolved_scope(self):
        session = {"predicted_files": ["auth/handler.py", "auth/tokens.py"]}
        results = check_boundaries(["auth/handler.py"], session, {"auth": {}})
        assert results == []

    def test_file_outside_resolved_scope(self):
        session = {"predicted_files": ["auth/handler.py"]}
        results = check_boundaries(["payments/billing.py"], session, {"auth": {}})
        assert len(results) == 1
        assert results[0].severity == Severity.NUDGE
        assert "payments/billing.py" in results[0].message

    def test_no_session_skips(self):
        results = check_boundaries(["anything.py"], None, {})
        assert results == []

    def test_empty_predicted_skips(self):
        results = check_boundaries(["x.py"], {"predicted_files": []}, {})
        assert results == []


# ---------------------------------------------------------------------------
# Contract check
# ---------------------------------------------------------------------------

class TestContractCheck:
    def test_both_sides_modified(self):
        invariants = {
            "contracts": [{
                "trigger_file": "billing.py",
                "coupled_file": "webhook.py",
                "confidence": 0.73,
            }],
        }
        results = check_contracts(["billing.py", "webhook.py"], invariants, "")
        assert results == []

    def test_one_side_modified(self):
        invariants = {
            "contracts": [{
                "trigger_file": "billing.py",
                "coupled_file": "webhook.py",
                "confidence": 0.73,
            }],
        }
        results = check_contracts(["billing.py"], invariants, "")
        assert len(results) == 1
        assert results[0].severity == Severity.NUDGE
        assert "webhook.py" in results[0].message

    def test_low_confidence_skipped(self):
        invariants = {
            "contracts": [{
                "trigger_file": "a.py",
                "coupled_file": "b.py",
                "confidence": 0.3,
            }],
        }
        results = check_contracts(["a.py"], invariants, "")
        assert results == []

    def test_fix_proposal_generated(self):
        invariants = {
            "contracts": [{
                "trigger_file": "billing.py",
                "coupled_file": "webhook.py",
                "confidence": 0.73,
            }],
            "function_co_changes": {},
        }
        results = check_contracts(["billing.py"], invariants, "")
        assert results[0].proposed_fix is not None
        assert results[0].proposed_fix.file == "webhook.py"


# ---------------------------------------------------------------------------
# Anti-pattern check
# ---------------------------------------------------------------------------

class TestAntiPatternCheck:
    def test_regex_match_added_lines(self):
        scopes = {
            "auth": {
                "anti_patterns": [{
                    "pattern": "\\.delete\\(\\)",
                    "replacement": ".deactivate()",
                    "scope_files": [],
                    "message": "Use .deactivate() instead of .delete()",
                }],
            },
        }
        added = {"auth/handler.py": ["user.delete()"]}
        results = check_antipatterns(added, scopes, "/tmp")
        assert len(results) == 1
        assert results[0].severity == Severity.NUDGE
        assert results[0].proposed_fix is not None

    def test_no_match(self):
        scopes = {
            "auth": {
                "anti_patterns": [{
                    "pattern": "\\.delete\\(\\)",
                    "scope_files": [],
                    "message": "no delete",
                }],
            },
        }
        added = {"auth/handler.py": ["user.deactivate()"]}
        results = check_antipatterns(added, scopes, "/tmp")
        assert results == []

    def test_scope_files_targeting(self):
        scopes = {
            "auth": {
                "anti_patterns": [{
                    "pattern": "\\.delete\\(\\)",
                    "scope_files": ["models/user.py"],
                    "message": "no delete",
                }],
            },
        }
        # File not in scope_files
        added = {"auth/handler.py": ["user.delete()"]}
        results = check_antipatterns(added, scopes, "/tmp")
        assert results == []

        # File in scope_files
        added2 = {"models/user.py": ["user.delete()"]}
        results2 = check_antipatterns(added2, scopes, "/tmp")
        assert len(results2) == 1


# ---------------------------------------------------------------------------
# Stability check
# ---------------------------------------------------------------------------

class TestStabilityCheck:
    def test_stable_file_large_change(self):
        invariants = {
            "file_stabilities": {
                "auth/oauth.py": {"classification": "stable", "commit_count": 3},
            },
        }
        # Build a diff with >20 added lines
        diff_lines = ["diff --git a/auth/oauth.py b/auth/oauth.py"]
        diff_lines.extend(["+line" for _ in range(25)])
        diff_text = "\n".join(diff_lines)

        results = check_stability(["auth/oauth.py"], diff_text, invariants)
        assert len(results) == 1
        assert results[0].severity == Severity.NOTE

    def test_volatile_file_ignored(self):
        invariants = {
            "file_stabilities": {
                "api/routes.py": {"classification": "volatile", "commit_count": 50},
            },
        }
        diff_lines = ["diff --git a/api/routes.py b/api/routes.py"]
        diff_lines.extend(["+line" for _ in range(30)])
        diff_text = "\n".join(diff_lines)

        results = check_stability(["api/routes.py"], diff_text, invariants)
        assert results == []


# ---------------------------------------------------------------------------
# Intent checks
# ---------------------------------------------------------------------------

class TestIntentChecks:
    def test_freeze_any_change_hold(self):
        intents = [IntentDirective(
            directive="freeze", modules=["core/"],
            reason="Stable module", id="abc",
        )]
        results = check_intent_holds(["core/engine.py"], {}, intents)
        assert len(results) == 1
        assert results[0].severity == Severity.GUARD

    def test_deprecate_new_usage_hold(self):
        intents = [IntentDirective(
            directive="deprecate",
            files=["utils/legacy.py"],
            replacement="utils/helpers.py",
            reason="Migrating", id="dep1",
        )]
        added = {"api/routes.py": ["from utils.legacy import old_func"]}
        results = check_intent_holds([], added, intents)
        assert len(results) == 1
        assert results[0].proposed_fix is not None
        assert results[0].proposed_fix.file == "utils/helpers.py"

    def test_decouple_new_coupling_note(self):
        intents = [IntentDirective(
            directive="decouple",
            modules=["auth/", "payments/"],
            reason="Separate concerns", id="dc1", set_at="2026-03-20",
        )]
        added = {"auth/handler.py": ["from payments import billing"]}
        results = check_intent_notes([], added, intents)
        assert len(results) == 1
        assert results[0].severity == Severity.NOTE

    def test_consolidate_wrong_direction_note(self):
        intents = [IntentDirective(
            directive="consolidate",
            modules=["api/v1/", "api/v2/"],
            target="api/",
            reason="Merging", id="con1", set_at="2026-03-18",
        )]
        results = check_intent_notes(["api/v1/routes.py"], {}, intents)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Acknowledge
# ---------------------------------------------------------------------------

class TestAcknowledge:
    def test_record_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_acknowledgment(tmp, "ack_123", "legitimate one-off")
            acks = load_acknowledgments(tmp)
            assert len(acks) == 1
            assert acks[0]["id"] == "ack_123"

    def test_confidence_decay(self):
        import time
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        acks = [{"id": "x", "timestamp": ts} for _ in range(5)]
        decayed = compute_decayed_confidence(0.8, "x", acks)
        assert decayed < 0.8  # 5 > threshold of 3

    def test_min_confidence_floor(self):
        import time
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        acks = [{"id": "x", "timestamp": ts} for _ in range(100)]
        decayed = compute_decayed_confidence(0.8, "x", acks)
        assert decayed >= 0.3  # Min floor


# ---------------------------------------------------------------------------
# Constraints builder
# ---------------------------------------------------------------------------

class TestConstraints:
    def test_filters_to_scope(self):
        invariants = {
            "contracts": [
                {"trigger_file": "auth/handler.py", "coupled_file": "api/routes.py", "confidence": 0.8},
                {"trigger_file": "payments/billing.py", "coupled_file": "payments/webhook.py", "confidence": 0.9},
            ],
            "file_stabilities": {},
        }
        constraints = build_constraints(
            "auth", "/tmp", invariants, {}, [],
        )
        # Should include the auth contract but not the payments one
        assert any("auth/handler.py" in c.message for c in constraints)
        assert not any("payments/billing.py" in c.message for c in constraints)

    def test_cap_at_5_per_category(self):
        contracts = [
            {"trigger_file": f"auth/file{i}.py", "coupled_file": f"api/file{i}.py", "confidence": 0.8}
            for i in range(10)
        ]
        invariants = {"contracts": contracts, "file_stabilities": {}}
        constraints = build_constraints("auth", "/tmp", invariants, {}, [])
        contract_count = sum(1 for c in constraints if c.category == "contract")
        assert contract_count <= 5


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_parse_diff(self):
        diff = (
            "diff --git a/auth/handler.py b/auth/handler.py\n"
            "--- a/auth/handler.py\n"
            "+++ b/auth/handler.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+import os\n"
            " existing line\n"
        )
        files, added = _parse_diff(diff)
        assert "auth/handler.py" in files
        assert "import os" in added["auth/handler.py"]

    def test_all_clear(self):
        report = check_diff("", "/tmp")
        assert report.passed

    def test_format_terminal_clear(self):
        report = CheckReport(passed=True, files_checked=3, checks_run=7)
        output = format_terminal(report)
        assert "clear" in output

    def test_format_terminal_nudge(self):
        report = CheckReport(
            passed=True,
            files_checked=2,
            checks_run=7,
            results=[
                CheckResult(
                    passed=False, category=CheckCategory.CONTRACT,
                    severity=Severity.NUDGE, message="billing.py without webhook.py",
                ),
            ],
        )
        output = format_terminal(report)
        assert "NUDGE" in output
        assert "billing.py" in output
        assert "guidance, not gates" in output

    def test_format_terminal_guard(self):
        report = CheckReport(
            passed=False,
            files_checked=1,
            checks_run=7,
            results=[
                CheckResult(
                    passed=False, category=CheckCategory.INTENT,
                    severity=Severity.GUARD, message="core/ is frozen",
                    can_acknowledge=True, acknowledge_id="ack_1",
                ),
            ],
        )
        output = format_terminal(report)
        assert "GUARD" in output
        assert "address guards" in output


# ---------------------------------------------------------------------------
# Intent file I/O
# ---------------------------------------------------------------------------

class TestIntent:
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            from dotscope.intent import add_intent, load_intents, remove_intent

            intent = add_intent(tmp, "freeze", ["core/"], reason="Stable")
            loaded = load_intents(tmp)
            assert len(loaded) == 1
            assert loaded[0].directive == "freeze"

            removed = remove_intent(tmp, intent.id)
            assert removed
            assert load_intents(tmp) == []
