"""Tests for experience design: counterfactuals and onboarding."""

import tempfile
import time

import pytest

from dotscope.onboarding import (
    load_onboarding, save_onboarding, mark_milestone, increment_counter,
    should_show_counterfactuals, should_show_health_nudges,
    next_step, milestone_message, version_control_tip, mark_vc_tip_shown,
)
from dotscope.counterfactual import (
    Counterfactual, compute_counterfactuals, format_counterfactuals_terminal,
    _has_new_coupling,
)


# ---------------------------------------------------------------------------
# Onboarding state
# ---------------------------------------------------------------------------

class TestOnboarding:
    def test_default_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = load_onboarding(tmp)
            assert state["first_ingest"] is None
            assert state["sessions_completed"] == 0

    def test_mark_milestone(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = mark_milestone(tmp, "first_ingest")
            assert state["first_ingest"] is not None
            # Marking again doesn't change it
            original = state["first_ingest"]
            state2 = mark_milestone(tmp, "first_ingest")
            assert state2["first_ingest"] == original

    def test_increment_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            increment_counter(tmp, "sessions_completed")
            increment_counter(tmp, "sessions_completed")
            state = load_onboarding(tmp)
            assert state["sessions_completed"] == 2

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"first_ingest": "2026-03-25T10:00:00Z", "sessions_completed": 5}
            save_onboarding(tmp, state)
            loaded = load_onboarding(tmp)
            assert loaded["first_ingest"] == "2026-03-25T10:00:00Z"
            assert loaded["sessions_completed"] == 5


# ---------------------------------------------------------------------------
# Gating rules
# ---------------------------------------------------------------------------

class TestGating:
    def test_counterfactuals_gated(self):
        assert not should_show_counterfactuals({"observations_recorded": 0})
        assert not should_show_counterfactuals({"observations_recorded": 2})
        assert should_show_counterfactuals({"observations_recorded": 3})

    def test_health_nudges_gated_by_time(self):
        assert not should_show_health_nudges({"first_ingest": None})
        # Recent ingest — no nudges
        recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        assert not should_show_health_nudges({"first_ingest": recent})
        # Old ingest — show nudges
        assert should_show_health_nudges({"first_ingest": "2020-01-01T00:00:00Z"})


# ---------------------------------------------------------------------------
# Next step prompts
# ---------------------------------------------------------------------------

class TestNextStep:
    def test_after_ingest(self):
        state = {"first_ingest": "2026-03-25", "first_backtest": None}
        ns = next_step(state)
        assert "backtest" in ns

    def test_after_backtest(self):
        state = {"first_backtest": "2026-03-25", "conventions_reviewed": None, "first_session": None}
        ns = next_step(state)
        assert "conventions" in ns.lower()

    def test_after_conventions(self):
        state = {"first_backtest": "x", "conventions_reviewed": "x", "voice_reviewed": None, "first_session": None}
        ns = next_step(state)
        assert "voice" in ns.lower()

    def test_after_voice(self):
        state = {"first_backtest": "x", "conventions_reviewed": "x", "voice_reviewed": "x", "first_session": None}
        ns = next_step(state)
        assert "agent" in ns.lower() or "mcp" in ns.lower()

    def test_after_session(self):
        state = {"first_backtest": "x", "conventions_reviewed": "x", "voice_reviewed": "x", "first_session": "x", "hook_installed": None}
        ns = next_step(state)
        assert "hook" in ns

    def test_fully_onboarded(self):
        state = {"first_backtest": "x", "conventions_reviewed": "x", "voice_reviewed": "x", "first_session": "x", "hook_installed": "x"}
        assert next_step(state) is None


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

class TestMilestones:
    def test_first_session(self):
        msg = milestone_message({"sessions_completed": 1, "observations_recorded": 0})
        assert "First session" in msg

    def test_first_observation(self):
        msg = milestone_message({"sessions_completed": 2, "observations_recorded": 1})
        assert "Feedback loop" in msg

    def test_five_sessions(self):
        msg = milestone_message({"sessions_completed": 5, "observations_recorded": 3})
        assert "5 sessions" in msg

    def test_no_milestone(self):
        assert milestone_message({"sessions_completed": 3, "observations_recorded": 2}) is None


# ---------------------------------------------------------------------------
# Version control tip
# ---------------------------------------------------------------------------

class TestVCTip:
    def test_shown_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = load_onboarding(tmp)
            tip = version_control_tip(state)
            assert tip is not None
            assert ".scope" in tip

            mark_vc_tip_shown(tmp)
            state2 = load_onboarding(tmp)
            assert version_control_tip(state2) is None


# ---------------------------------------------------------------------------
# Counterfactuals
# ---------------------------------------------------------------------------

class TestCounterfactuals:
    def test_near_miss_becomes_counterfactual(self):
        nms = [{"event": "Used .deactivate() instead of .delete()", "scope": "auth"}]
        cfs = compute_counterfactuals(
            constraints_served=[], modified_files=set(),
            diff_text="", near_misses=nms,
        )
        assert len(cfs) == 1
        assert cfs[0].type == "anti_pattern_avoided"

    def test_contract_honored(self):
        constraints = [
            {"category": "contract", "message": "If you modify billing.py, review webhook.py"}
        ]
        invariants = {
            "contracts": [{
                "trigger_file": "billing.py",
                "coupled_file": "webhook.py",
                "confidence": 0.73,
            }],
        }
        cfs = compute_counterfactuals(
            constraints_served=constraints,
            modified_files={"billing.py", "webhook.py"},
            diff_text="",
            invariants=invariants,
        )
        assert any(cf.type == "contract_honored" for cf in cfs)

    def test_contract_not_served_is_not_counterfactual(self):
        """If the contract wasn't in the constraints, it's coincidence."""
        invariants = {
            "contracts": [{
                "trigger_file": "billing.py",
                "coupled_file": "webhook.py",
                "confidence": 0.73,
            }],
        }
        cfs = compute_counterfactuals(
            constraints_served=[],  # No contracts served
            modified_files={"billing.py", "webhook.py"},
            diff_text="",
            invariants=invariants,
        )
        assert not any(cf.type == "contract_honored" for cf in cfs)

    def test_intent_respected(self):
        from dotscope.check.models import IntentDirective
        constraints = [
            {"category": "intent", "message": "decouple auth/, payments/"}
        ]
        intents = [IntentDirective(
            directive="decouple", modules=["auth/", "payments/"],
        )]
        # Agent modified auth/ without new coupling
        cfs = compute_counterfactuals(
            constraints_served=constraints,
            modified_files={"auth/handler.py"},
            diff_text="diff --git a/auth/handler.py b/auth/handler.py\n+import os\n",
            intents=intents,
        )
        assert any(cf.type == "intent_respected" for cf in cfs)

    def test_has_new_coupling(self):
        diff = (
            "diff --git a/auth/handler.py b/auth/handler.py\n"
            "+from payments import billing\n"
        )
        assert _has_new_coupling(["auth/", "payments/"], diff)

    def test_no_new_coupling(self):
        diff = (
            "diff --git a/auth/handler.py b/auth/handler.py\n"
            "+import os\n"
        )
        assert not _has_new_coupling(["auth/", "payments/"], diff)

    def test_format_terminal(self):
        cfs = [
            Counterfactual("anti_pattern_avoided", "Used .deactivate()", "auth scope", "high"),
        ]
        output = format_counterfactuals_terminal(cfs)
        assert "prevented" in output
        assert ".deactivate()" in output

    def test_empty_returns_empty(self):
        assert format_counterfactuals_terminal([]) == ""
