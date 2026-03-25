"""Tests for utility scoring."""

import time
from dotscope.utility import compute_utility_scores, effective_score, FileUtilityScore
from dotscope.models import SessionLog, ObservationLog


class TestUtilityScoring:
    def test_basic_scoring(self):
        sessions = [
            SessionLog("s1", time.time(), "auth", "fix", ["a.py", "b.py"], ""),
            SessionLog("s2", time.time(), "auth", "fix", ["a.py", "c.py"], ""),
        ]
        observations = [
            ObservationLog("c1", "s1", ["a.py"], [], [], 1.0, 1.0, time.time()),
            ObservationLog("c2", "s2", ["a.py", "c.py"], [], [], 1.0, 1.0, time.time()),
        ]

        scores = compute_utility_scores(sessions, observations)
        assert scores["a.py"].resolve_count == 2
        assert scores["a.py"].touch_count == 2
        assert scores["a.py"].utility_ratio == 1.0

        assert scores["b.py"].resolve_count == 1
        assert scores["b.py"].touch_count == 0
        assert scores["b.py"].utility_ratio == 0.0

    def test_effective_score_with_floor(self):
        utility = FileUtilityScore("x.py", resolve_count=10, touch_count=0, utility_ratio=0.0)
        score = effective_score(1.0, utility, is_explicit_include=True)
        assert score >= 0.5  # Floor protects explicit includes

    def test_effective_score_boosts_high_utility(self):
        utility = FileUtilityScore(
            "x.py", resolve_count=10, touch_count=8, utility_ratio=0.8,
            last_touched=time.time(),
        )
        score = effective_score(1.0, utility, is_explicit_include=True)
        assert score > 1.0  # Should be boosted

    def test_no_utility_data(self):
        score = effective_score(1.0, None, is_explicit_include=True)
        assert score == 0.5  # Just the floor

    def test_min_sample_size(self):
        utility = FileUtilityScore("x.py", resolve_count=1, touch_count=1, utility_ratio=1.0)
        score = effective_score(1.0, utility, is_explicit_include=False)
        assert score == 1.0  # Not enough samples, no bonus applied
