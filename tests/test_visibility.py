"""Tests for the DX visibility features."""

import time
from dotscope.visibility import (
    SessionTracker,
    extract_attribution_hints,
    format_observation_delta,
    build_accuracy,
    check_health_nudges,
    detect_near_misses,
)
from dotscope.models import ObservationLog


def _make_response(token_count=1420, repo_tokens=47000, context="JWT tokens...",
                    hints=None, warnings=None):
    """Build a realistic resolve_scope response dict for testing."""
    return {
        "token_count": token_count,
        "_repo_tokens": repo_tokens,
        "context": context,
        "attribution_hints": hints or [{"hint": "soft deletes", "source": "hand_authored"}],
        "health_warnings": warnings or [],
    }


class TestSessionTracker:
    def test_empty_session(self):
        t = SessionTracker()
        s = t.summary()
        assert s["scopes_resolved"] == 0
        assert s["unique_scopes"] == 0
        assert s["started_at"] is None

    def test_single_resolve(self):
        t = SessionTracker()
        t.record_resolve("auth/", _make_response())
        s = t.summary()
        assert s["scopes_resolved"] == 1
        assert s["unique_scopes"] == 1
        assert s["tokens_served"] == 1420
        assert s["tokens_available"] == 47000
        assert s["reduction_pct"] == 97.0
        assert s["attribution_hints_served"] == 1
        assert s["started_at"] is not None

    def test_multiple_resolves_same_scope(self):
        t = SessionTracker()
        for _ in range(3):
            t.record_resolve("auth/", _make_response())
        s = t.summary()
        assert s["scopes_resolved"] == 3
        assert s["unique_scopes"] == 1
        assert s["tokens_served"] == 4260

    def test_multiple_different_scopes(self):
        t = SessionTracker()
        t.record_resolve("auth/", _make_response())
        t.record_resolve("api/", _make_response(token_count=2000))
        s = t.summary()
        assert s["scopes_resolved"] == 2
        assert s["unique_scopes"] == 2

    def test_terminal_format_nonempty(self):
        t = SessionTracker()
        t.record_resolve("auth/", _make_response())
        output = t.format_terminal()
        assert "1 scope resolved" in output
        assert "1,420 tokens" in output
        assert "97% reduction" in output
        assert "1 attribution hint" in output

    def test_terminal_format_empty_session(self):
        t = SessionTracker()
        assert t.format_terminal() == ""

    def test_health_warnings_tracked(self):
        t = SessionTracker()
        t.record_resolve("auth/", _make_response(
            warnings=[{"issue": "accuracy_degraded"}],
        ))
        s = t.summary()
        assert s["health_warnings_surfaced"] == 1

    def test_reset(self):
        t = SessionTracker()
        t.record_resolve("auth/", _make_response())
        t.reset()
        s = t.summary()
        assert s["scopes_resolved"] == 0
        assert s["unique_scopes"] == 0
        assert s["started_at"] is None


class TestAttributionHints:
    def test_extracts_warning_keywords_with_provenance(self):
        context = (
            "## Gotchas\n"
            "- Never call .delete() on User, use .deactivate() instead\n"
            "- Always validate tokens before refresh\n"
            "- Simple line with no keywords\n"
        )
        hints = extract_attribution_hints(context)
        assert len(hints) >= 2
        # Hints are now dicts with hint + source
        assert all("hint" in h and "source" in h for h in hints)
        assert any("delete" in h["hint"].lower() for h in hints)
        assert any(h["source"] == "hand_authored" for h in hints)

    def test_empty_context(self):
        assert extract_attribution_hints("") == []
        assert extract_attribution_hints("# just a heading") == []

    def test_includes_co_change_with_git_history_source(self):
        context = "billing.py and webhook_handler.py have 73% co-change rate"
        hints = extract_attribution_hints(context)
        assert len(hints) == 1
        assert "co-change" in hints[0]["hint"]
        assert hints[0]["source"] == "git_history"

    def test_signal_comment_source(self):
        context = "WARNING: this module is fragile after migration"
        hints = extract_attribution_hints(context)
        assert len(hints) == 1
        assert hints[0]["source"] == "signal_comment"


class TestObservationDelta:
    def test_formats_good_prediction(self):
        obs = ObservationLog(
            commit_hash="abc12345",
            session_id="sess1",
            actual_files_modified=["auth/handler.py", "auth/tokens.py"],
            predicted_not_touched=["auth/utils.py"],
            touched_not_predicted=[],
            recall=1.0,
            precision=0.67,
            timestamp=time.time(),
        )
        delta = format_observation_delta(obs, "auth")
        assert "auth/" in delta
        assert "2/2" in delta

    def test_formats_degraded_prediction(self):
        obs = ObservationLog(
            commit_hash="abc12345",
            session_id="sess1",
            actual_files_modified=["pay/a.py", "pay/b.py", "pay/c.py"],
            predicted_not_touched=[],
            touched_not_predicted=["pay/b.py", "pay/c.py"],
            recall=0.33,
            precision=1.0,
            timestamp=time.time(),
        )
        delta = format_observation_delta(obs, "payments")
        assert "degraded" in delta
        assert "Missing:" in delta


class TestAccuracy:
    def test_no_observations(self):
        assert build_accuracy([], "auth") is None

    def test_single_observation(self):
        obs = ObservationLog(
            commit_hash="abc",
            session_id="s1",
            actual_files_modified=["a.py"],
            touched_not_predicted=["b.py"],
            recall=0.5,
            precision=1.0,
            timestamp=time.time() - 3600,
        )
        result = build_accuracy([obs], "auth")
        assert result is not None
        assert result["observations"] == 1
        assert result["avg_recall"] == 0.5
        assert result["avg_precision"] == 1.0
        assert result["trend"] == "stable"
        assert "last_observation" in result
        assert result["lessons_applied"] == 1  # One missed file = one lesson

    def test_improving_trend(self):
        obs = [
            ObservationLog(commit_hash=f"c{i}", session_id=f"s{i}",
                          recall=0.6, precision=0.8, timestamp=float(i))
            for i in range(5)
        ] + [
            ObservationLog(commit_hash=f"d{i}", session_id=f"s{i+5}",
                          recall=0.95, precision=0.95, timestamp=float(i + 5))
            for i in range(5)
        ]
        result = build_accuracy(obs, "auth")
        assert result["trend"] == "improving"

    def test_no_lessons_when_perfect(self):
        obs = ObservationLog(
            commit_hash="abc",
            session_id="s1",
            touched_not_predicted=[],  # Perfect prediction
            recall=1.0,
            precision=1.0,
            timestamp=time.time(),
        )
        result = build_accuracy([obs], "auth")
        assert "lessons_applied" not in result  # No lessons needed


class TestHealthNudges:
    def test_no_nudge_for_few_observations(self):
        obs = [
            ObservationLog(commit_hash="a", session_id="s1", recall=0.5, timestamp=0),
        ]
        assert check_health_nudges(obs, "auth") == []

    def test_nudge_on_degradation(self):
        obs = [
            ObservationLog(commit_hash=f"c{i}", session_id=f"s{i}",
                          recall=0.95, timestamp=float(i))
            for i in range(5)
        ] + [
            ObservationLog(commit_hash=f"d{i}", session_id=f"s{i+5}",
                          recall=0.65, timestamp=float(i + 5))
            for i in range(5)
        ]
        nudges = check_health_nudges(obs, "payments")
        assert len(nudges) == 1
        assert nudges[0]["issue"] == "accuracy_degraded"
        assert nudges[0]["current_accuracy"] < nudges[0]["previous_accuracy"]


class TestNearMissDetection:
    def test_detects_soft_delete_near_miss(self):
        context = "User model has soft deletes. Never call .delete(), use .deactivate()."
        diff = "user.deactivate()\nuser.save()"
        nms = detect_near_misses(context, diff, "auth")
        assert len(nms) >= 1

    def test_no_near_miss_when_anti_pattern_present(self):
        context = "Never call .delete(), use .deactivate()."
        diff = "user.delete()\n"  # Anti-pattern IS present
        nms = detect_near_misses(context, diff, "auth")
        # Should not flag this — the agent DID use the anti-pattern
        soft_delete_nms = [nm for nm in nms if ".delete" in nm.get("scope_context_used", "").lower()]
        assert len(soft_delete_nms) == 0

    def test_empty_inputs(self):
        assert detect_near_misses("", "", "auth") == []
        assert detect_near_misses("context", "", "auth") == []
