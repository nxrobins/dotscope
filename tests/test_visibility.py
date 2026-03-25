"""Tests for the DX visibility features."""

import time
from dotscope.visibility import (
    SessionTracker,
    extract_attribution_hints,
    compute_source_signals,
    format_observation_delta,
    build_recent_learning,
    check_health_nudges,
    detect_near_misses,
)
from dotscope.models import ObservationLog


class TestSessionTracker:
    def test_empty_session(self):
        t = SessionTracker()
        s = t.summary()
        assert s["scopes_resolved"] == 0
        assert s["observations_pending"] is False

    def test_tracks_resolves(self):
        t = SessionTracker()
        t.record_resolve(1500, 50000, True)
        t.record_resolve(2000, 50000, False)
        s = t.summary()
        assert s["scopes_resolved"] == 2
        assert s["tokens_served"] == 3500
        assert s["tokens_available"] == 50000
        assert s["reduction_pct"] == 93
        assert s["implicit_contracts_applied"] == 1
        assert s["context_fields_used"] == 2

    def test_terminal_format(self):
        t = SessionTracker()
        assert t.format_terminal() == ""  # Empty when no resolves
        t.record_resolve(1000, 10000, False)
        output = t.format_terminal()
        assert "1 scopes resolved" in output
        assert "1,000 tokens served" in output


class TestAttributionHints:
    def test_extracts_warning_keywords(self):
        context = (
            "## Gotchas\n"
            "- Never call .delete() on User, use .deactivate() instead\n"
            "- Always validate tokens before refresh\n"
            "- Simple line with no keywords\n"
        )
        hints = extract_attribution_hints(context)
        assert len(hints) >= 2
        assert any("delete" in h.lower() for h in hints)
        assert any("validate" in h.lower() or "always" in h.lower() for h in hints)

    def test_empty_context(self):
        assert extract_attribution_hints("") == []
        assert extract_attribution_hints("# just a heading") == []

    def test_includes_co_change(self):
        context = "billing.py and webhook_handler.py have 73% co-change rate"
        hints = extract_attribution_hints(context)
        assert len(hints) == 1
        assert "co-change" in hints[0]


class TestSourceSignals:
    def test_detects_git_history(self):
        context = "## Implicit Contracts (from git history)\n- billing changes"
        signals = compute_source_signals(context)
        assert signals.get("from_git_history", 0) > 0

    def test_empty_context(self):
        signals = compute_source_signals("")
        assert "hand_authored" in signals


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


class TestRecentLearning:
    def test_no_observations(self):
        assert build_recent_learning([], "auth") is None

    def test_recent_observation(self):
        obs = ObservationLog(
            commit_hash="abc",
            session_id="s1",
            actual_files_modified=["a.py"],
            touched_not_predicted=["b.py"],
            recall=0.5,
            precision=1.0,
            timestamp=time.time() - 3600,  # 1 hour ago
        )
        result = build_recent_learning([obs], "auth")
        assert result is not None
        assert "1h ago" in result["last_observation"]
        assert result["recent_accuracy"] == 0.5
        assert "note" in result  # Should note the missed file

    def test_old_observation_ignored(self):
        obs = ObservationLog(
            commit_hash="abc",
            session_id="s1",
            recall=0.9,
            precision=0.9,
            timestamp=time.time() - 100000,  # >24h ago
        )
        assert build_recent_learning([obs], "auth") is None


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
