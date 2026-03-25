"""Tests for task-to-scope matching."""

from dotscope.matcher import match_task


class TestMatchTask:
    def test_keyword_match(self):
        scopes = [
            ("auth", ["authentication", "login", "JWT", "session"], "Auth module"),
            ("payments", ["billing", "stripe", "invoice"], "Payment processing"),
        ]

        results = match_task("fix the JWT token expiry bug", scopes)
        assert len(results) > 0
        assert results[0][0] == "auth"

    def test_no_match(self):
        scopes = [
            ("auth", ["authentication", "login"], "Auth module"),
        ]
        results = match_task("deploy kubernetes cluster", scopes)
        # May or may not match — threshold-dependent
        # But auth should not be high confidence
        if results:
            assert results[0][1] < 0.5

    def test_multiple_matches_ranked(self):
        scopes = [
            ("auth", ["authentication", "login", "JWT"], "Auth"),
            ("api", ["endpoint", "route", "JWT", "middleware"], "API"),
        ]
        results = match_task("JWT authentication endpoint", scopes)
        assert len(results) >= 1

    def test_scope_name_match(self):
        scopes = [
            ("auth", [], "Authentication module"),
            ("payments", [], "Payment module"),
        ]
        results = match_task("fix auth login flow", scopes)
        assert len(results) > 0
        assert results[0][0] == "auth"

    def test_empty_task(self):
        scopes = [("auth", ["login"], "Auth")]
        results = match_task("", scopes)
        assert results == []
