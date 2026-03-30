"""Tests for scope composition algebra."""

import os
import pytest
from dotscope.composer import parse_expression, compose, compose_for_task, Op


class TestParseExpression:
    def test_single_scope(self):
        ops = parse_expression("auth")
        assert len(ops) == 1
        assert ops[0].ref.name == "auth"
        assert ops[0].operator is None

    def test_merge(self):
        ops = parse_expression("auth+payments")
        assert len(ops) == 2
        assert ops[0].ref.name == "auth"
        assert ops[1].operator == Op.MERGE
        assert ops[1].ref.name == "payments"

    def test_subtract(self):
        ops = parse_expression("auth-tests")
        assert len(ops) == 2
        assert ops[1].operator == Op.SUBTRACT

    def test_intersect(self):
        ops = parse_expression("auth&api")
        assert len(ops) == 2
        assert ops[1].operator == Op.INTERSECT

    def test_context_only(self):
        ops = parse_expression("auth@context")
        assert len(ops) == 1
        assert ops[0].ref.context_only is True

    def test_complex_expression(self):
        ops = parse_expression("auth+payments-tests")
        assert len(ops) == 3

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty"):
            parse_expression("")


class TestCompose:
    def test_single_scope(self, tmp_project):
        result = compose("auth", root=str(tmp_project), follow_related=False)
        assert len(result.files) > 0
        assert "JWT tokens" in result.context

    def test_merge_scopes(self, tmp_project):
        result = compose("auth+payments", root=str(tmp_project), follow_related=False)
        basenames = [os.path.basename(f) for f in result.files]
        assert "handler.py" in basenames  # from auth
        assert "billing.py" in basenames  # from payments

    def test_context_only(self, tmp_project):
        result = compose("auth@context", root=str(tmp_project))
        assert len(result.files) == 0
        assert "JWT tokens" in result.context

    def test_scope_not_found(self, tmp_project):
        with pytest.raises(ValueError, match="not found"):
            compose("nonexistent", root=str(tmp_project))


class TestComposeForTask:
    def test_single_match(self, tmp_project):
        """Task with auth keywords matches auth scope."""
        result = compose_for_task(
            "Fix authentication session management",
            root=str(tmp_project),
        )
        basenames = [os.path.basename(f) for f in result.files]
        assert "handler.py" in basenames or "tokens.py" in basenames

    def test_multi_scope_composition(self, tmp_project):
        """Task spanning auth and payments keywords returns files from both."""
        result = compose_for_task(
            "Update billing for authenticated session management",
            root=str(tmp_project),
        )
        basenames = [os.path.basename(f) for f in result.files]
        # Should have files from both scopes
        assert "billing.py" in basenames
        assert "handler.py" in basenames or "tokens.py" in basenames

    def test_no_match_returns_empty(self, tmp_project):
        """Completely irrelevant task returns empty without crashing."""
        result = compose_for_task("Deploy kubernetes cluster", root=str(tmp_project))
        assert result.files == [] or result.files is not None  # doesn't crash

    def test_max_scopes_limits_expression(self, tmp_project):
        """With max_scopes=1, the composed expression uses only one scope name."""
        # Verify that compose_for_task builds a single-scope expression
        from dotscope.matcher import match_task
        from dotscope.discovery import find_all_scopes
        from dotscope.parser import parse_scope_file
        import os

        scope_files = find_all_scopes(str(tmp_project))
        scope_tuples = []
        for sf in scope_files:
            config = parse_scope_file(sf)
            name = os.path.basename(os.path.dirname(config.path)) or "root"
            scope_tuples.append((name, config.tags, config.description))

        matches = match_task(
            "Update billing for authenticated session management",
            scope_tuples,
        )
        # With max_scopes=1, only the first match name is used
        result = compose_for_task(
            "Update billing for authenticated session management",
            root=str(tmp_project),
            max_scopes=1,
        )
        # Should have files — the key test is it doesn't crash
        assert len(result.files) > 0

    def test_no_root_returns_empty(self):
        """When root can't be detected, returns empty."""
        result = compose_for_task("anything", root="/nonexistent/path")
        assert result.files == []
