"""Tests for the explain module: warning provenance assembly."""

import json
import os

import pytest

from dotscope.explain import (
    explain_warning,
    format_explanation,
    _count_precedents,
    _was_acknowledged,
)
from dotscope.models.intent import CheckCategory, CheckResult, Severity


class TestExplainWarning:
    def test_basic_fields_populated(self, tmp_path):
        result = CheckResult(
            passed=False,
            category=CheckCategory.CONTRACT,
            severity=Severity.NUDGE,
            message="a and b usually change together",
            source_file="invariants.json",
            source_rule="contract:a\u2194b",
        )
        explanation = explain_warning(str(tmp_path), result)

        assert explanation["source"] == "invariants.json"
        assert explanation["rule"] == "contract:a\u2194b"
        assert explanation["evidence"] == "a and b usually change together"
        assert explanation["precedent_count"] == 0
        assert explanation["acknowledged_before"] is False

    def test_unknown_source_when_missing(self, tmp_path):
        result = CheckResult(
            passed=False,
            category=CheckCategory.CONTRACT,
            severity=Severity.NUDGE,
            message="test",
        )
        explanation = explain_warning(str(tmp_path), result)
        assert explanation["source"] == "unknown"
        assert explanation["rule"] == "unknown"

    def test_precedent_and_ack_populated(self, tmp_path):
        dotscope = tmp_path / ".dotscope"
        dotscope.mkdir()
        (dotscope / "nudge_occurrences.jsonl").write_text(
            json.dumps({"acknowledge_id": "ack-1"}) + "\n"
            + json.dumps({"acknowledge_id": "ack-1"}) + "\n"
        )
        (dotscope / "acknowledgments.jsonl").write_text(
            json.dumps({"acknowledge_id": "ack-1"}) + "\n"
        )

        result = CheckResult(
            passed=False,
            category=CheckCategory.CONTRACT,
            severity=Severity.NUDGE,
            message="co-change",
            acknowledge_id="ack-1",
            can_acknowledge=True,
        )
        explanation = explain_warning(str(tmp_path), result)
        assert explanation["precedent_count"] == 2
        assert explanation["acknowledged_before"] is True


class TestFormatExplanation:
    def test_basic_format(self):
        explanation = {
            "source": "invariants.json",
            "rule": "contract:a\u2194b",
            "rule_text": "Co-change confidence: 85%",
            "evidence": "a and b usually change together",
            "detail": "last 10 commits",
            "precedent_count": 3,
            "acknowledged_before": True,
            "suggestion": "Update both files",
        }
        text = format_explanation(explanation)
        assert "Source: invariants.json" in text
        assert "Rule: contract:a\u2194b" in text
        assert "Rule text: Co-change confidence: 85%" in text
        assert "Prior occurrences: 3" in text
        assert "Previously acknowledged: yes" in text
        assert "Suggestion: Update both files" in text

    def test_minimal_format(self):
        explanation = {
            "source": "unknown",
            "rule": "unknown",
            "rule_text": "",
            "evidence": "test",
            "detail": "",
            "precedent_count": 0,
            "acknowledged_before": False,
            "suggestion": "",
        }
        text = format_explanation(explanation)
        assert "Prior occurrences" not in text
        assert "Previously acknowledged" not in text
        assert "Suggestion" not in text


class TestCountPrecedents:
    def test_counts_matching_entries(self, tmp_path):
        dotscope = tmp_path / ".dotscope"
        dotscope.mkdir()
        lines = [
            json.dumps({"acknowledge_id": "id-a"}),
            json.dumps({"acknowledge_id": "id-b"}),
            json.dumps({"acknowledge_id": "id-a"}),
            json.dumps({"acknowledge_id": "id-a"}),
        ]
        (dotscope / "nudge_occurrences.jsonl").write_text("\n".join(lines) + "\n")

        assert _count_precedents(str(tmp_path), "id-a") == 3
        assert _count_precedents(str(tmp_path), "id-b") == 1
        assert _count_precedents(str(tmp_path), "id-missing") == 0

    def test_missing_file_returns_zero(self, tmp_path):
        assert _count_precedents(str(tmp_path), "anything") == 0


class TestWasAcknowledged:
    def test_found_in_file(self, tmp_path):
        dotscope = tmp_path / ".dotscope"
        dotscope.mkdir()
        lines = [
            json.dumps({"acknowledge_id": "ack-x"}),
            json.dumps({"acknowledge_id": "ack-y"}),
        ]
        (dotscope / "acknowledgments.jsonl").write_text("\n".join(lines) + "\n")

        assert _was_acknowledged(str(tmp_path), "ack-x") is True
        assert _was_acknowledged(str(tmp_path), "ack-z") is False

    def test_missing_file_returns_false(self, tmp_path):
        assert _was_acknowledged(str(tmp_path), "anything") is False
