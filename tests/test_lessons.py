"""Tests for lessons and constraints."""

import time
from dotscope.lessons import generate_lessons, detect_invariants, format_lessons_for_context
from dotscope.models import SessionLog, ObservationLog


class TestLessons:
    def test_detects_never_touched(self):
        """File resolved 10+ times but never modified → lesson."""
        sessions = [
            SessionLog(f"s{i}", time.time(), "auth", "fix", ["auth/config.py", "auth/handler.py"], "")
            for i in range(12)
        ]
        observations = [
            ObservationLog(f"c{i}", f"s{i}", ["auth/handler.py"], ["auth/config.py"], [], 0.5, 1.0, time.time())
            for i in range(12)
        ]

        lessons = generate_lessons(sessions, observations, module="auth")
        never_touched = [l for l in lessons if l.trigger == "resolved_never_touched"]
        assert len(never_touched) >= 1
        assert "config.py" in never_touched[0].lesson_text

    def test_detects_scope_gap(self):
        """File touched but not in scope 3+ times → lesson."""
        sessions = [
            SessionLog(f"s{i}", time.time(), "auth", "fix", ["auth/handler.py"], "")
            for i in range(5)
        ]
        observations = [
            ObservationLog(
                f"c{i}", f"s{i}",
                ["auth/handler.py", "models/user.py"],
                [], ["models/user.py"],
                0.5, 1.0, time.time()
            )
            for i in range(5)
        ]

        lessons = generate_lessons(sessions, observations, module="auth")
        gaps = [l for l in lessons if l.trigger == "touched_not_predicted"]
        assert len(gaps) >= 1
        assert "user.py" in gaps[0].lesson_text

    def test_detects_hotspot(self):
        """Most frequently modified file → lesson."""
        sessions = [
            SessionLog(f"s{i}", time.time(), "auth", "fix", ["auth/handler.py"], "")
            for i in range(6)
        ]
        observations = [
            ObservationLog(f"c{i}", f"s{i}", ["auth/handler.py"], [], [], 1.0, 1.0, time.time())
            for i in range(6)
        ]

        lessons = generate_lessons(sessions, observations, module="auth")
        hotspots = [l for l in lessons if l.trigger == "hotspot"]
        assert len(hotspots) >= 1

    def test_no_lessons_without_observations(self):
        sessions = [SessionLog("s1", time.time(), "auth", "fix", ["a.py"], "")]
        lessons = generate_lessons(sessions, [], module="auth")
        assert lessons == []


class TestInvariants:
    def test_detects_no_import_boundary(self):
        edges = [("auth/handler.py", "models/user.py")]
        invariants = detect_invariants(edges, "auth", ["auth", "payments", "models"], 100)
        # auth doesn't import from payments → invariant
        payments_inv = [inv for inv in invariants if "payments" in inv.boundary]
        assert len(payments_inv) >= 1
        assert payments_inv[0].direction == "no_import"

    def test_no_invariant_for_existing_import(self):
        edges = [("auth/handler.py", "models/user.py")]
        invariants = detect_invariants(edges, "auth", ["auth", "models"], 100)
        # auth DOES import from models → no invariant
        models_inv = [inv for inv in invariants if "models" in inv.boundary]
        assert len(models_inv) == 0

    def test_format_for_context(self):
        from dotscope.lessons import Lesson, ObservedInvariant
        lessons = [Lesson("test", "obs", "Important lesson", 0.9, time.time())]
        invariants = [ObservedInvariant("auth -> payments", "no_import", "", 500, 0.95)]

        text = format_lessons_for_context(lessons, invariants)
        assert "Lessons" in text
        assert "Boundaries" in text
        assert "auth -> payments" in text
