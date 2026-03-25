"""Tests for scope composition algebra."""

import os
import pytest
from dotscope.composer import parse_expression, compose, Op


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
