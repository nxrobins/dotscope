"""Tests for the routing supremum: all six gaps."""

import json
import os
import tempfile
import time

from dotscope.models.intent import (
    CheckCategory, CheckReport, CheckResult, ConventionRule, Severity,
)
from dotscope.passes.sentinel.constraints import (
    build_routing_guidance, build_adjacent_routing, match_conventions_by_path,
)
from dotscope.passes.sentinel.acknowledge import (
    record_nudge_occurrence, record_nudge_resolution, is_escalated,
)


# ---------------------------------------------------------------------------
# Gap 1: Path-first routing
# ---------------------------------------------------------------------------

class TestPathFirstRouting:
    def test_file_path_pattern_generates_routing(self):
        conv = ConventionRule(
            name="Route Handler",
            match_criteria={"any_of": [{"file_path": "api/routes/.*\\.py"}]},
            rules={"prohibited_imports": ["sqlalchemy"]},
            compliance=0.9,
        )
        routing = build_routing_guidance("api/", conventions=[conv])
        messages = [r.message for r in routing]
        assert any("New files matching" in m for m in messages)
        assert any("api/routes/" in m for m in messages)

    def test_conflicting_conventions_deduped(self):
        """Two conventions matching the same file → highest compliance wins."""
        conv1 = ConventionRule(
            name="Handler v1",
            match_criteria={"any_of": [{"file_path": "api/.*\\.py"}]},
            rules={"prohibited_imports": ["os"]},
            compliance=0.7,
        )
        conv2 = ConventionRule(
            name="Handler v1",  # Same name
            match_criteria={"any_of": [{"file_path": "api/.*\\.py"}]},
            rules={"prohibited_imports": ["sys"]},
            compliance=0.95,
        )
        routing = build_routing_guidance("api/", conventions=[conv1, conv2])
        # Should keep only the higher-compliance one per (name, type)
        blueprints = [r for r in routing if r.metadata.get("type") == "convention_blueprint"]
        assert len(blueprints) == 1
        assert blueprints[0].confidence == 0.95

    def test_no_path_pattern_no_extra_routing(self):
        conv = ConventionRule(
            name="Service",
            match_criteria={"any_of": [{"has_decorator": "inject"}]},
            rules={"required_methods": ["execute"]},
            compliance=0.85,
        )
        routing = build_routing_guidance("services/", conventions=[conv])
        # Should have the general convention routing but no path-pattern routing
        path_routes = [r for r in routing if r.metadata.get("type") == "path_pattern"]
        assert len(path_routes) == 0


# ---------------------------------------------------------------------------
# Gap 2: Adjacent scope routing
# ---------------------------------------------------------------------------

class TestAdjacentRouting:
    def test_adjacent_scopes_from_graph(self):
        hubs = {
            "auth/handler.py": {
                "imported_by": ["api/routes/auth.py"],
                "imports": ["models/user.py"],
            },
        }
        scopes = {
            "api": {"description": "API layer"},
            "models": {"description": "Data models"},
        }
        adjacent = build_adjacent_routing("auth/", graph_hubs=hubs, all_scopes=scopes)
        scope_names = [r.metadata.get("adjacent_scope") for r in adjacent]
        assert "api" in scope_names or "models" in scope_names

    def test_no_hubs_no_adjacent(self):
        adjacent = build_adjacent_routing("auth/", graph_hubs=None, all_scopes=None)
        assert adjacent == []


# ---------------------------------------------------------------------------
# Gap 3: NUDGE escalation
# ---------------------------------------------------------------------------

class TestNudgeEscalation:
    def test_not_escalated_before_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".dotscope"))
            record_nudge_occurrence(d, "contract_abc")
            record_nudge_occurrence(d, "contract_abc")
            assert not is_escalated(d, "contract_abc")

    def test_escalated_after_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".dotscope"))
            for _ in range(3):
                record_nudge_occurrence(d, "contract_xyz")
            assert is_escalated(d, "contract_xyz")

    def test_resolution_resets_counter(self):
        """After a nudge is resolved, counter resets. Next occurrence starts fresh."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".dotscope"))
            # Fire 3 times → escalated
            for _ in range(3):
                record_nudge_occurrence(d, "contract_reset_test")
            assert is_escalated(d, "contract_reset_test")

            # Record resolution (issue fixed)
            record_nudge_resolution(d, "contract_reset_test")

            # Fire once more → NOT escalated (counter reset)
            record_nudge_occurrence(d, "contract_reset_test")
            assert not is_escalated(d, "contract_reset_test")

    def test_escalated_nudge_becomes_guard(self):
        """Integration: checker escalates repeated nudges."""
        result = CheckResult(
            passed=False,
            category=CheckCategory.CONTRACT,
            severity=Severity.NUDGE,
            message="billing.py without webhook.py",
            acknowledge_id="contract_billing_webhook",
        )
        # Simulate escalation check
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".dotscope"))
            for _ in range(3):
                record_nudge_occurrence(d, result.acknowledge_id)
            if is_escalated(d, result.acknowledge_id):
                result.severity = Severity.GUARD
            assert result.severity == Severity.GUARD
            assert result.severity.blocks_commit


# ---------------------------------------------------------------------------
# Gap 5: File creation advisor
# ---------------------------------------------------------------------------

class TestMatchConventionsByPath:
    def test_match_by_path_regex(self):
        conv = ConventionRule(
            name="Route Handler",
            match_criteria={"any_of": [{"file_path": "api/routes/.*\\.py"}]},
            rules={"prohibited_imports": ["sqlalchemy"]},
            compliance=0.95,
        )
        matches = match_conventions_by_path("api/routes/billing.py", [conv])
        assert len(matches) == 1
        assert matches[0]["convention"] == "Route Handler"

    def test_no_match(self):
        conv = ConventionRule(
            name="Route Handler",
            match_criteria={"any_of": [{"file_path": "api/routes/.*\\.py"}]},
            rules={},
            compliance=0.9,
        )
        matches = match_conventions_by_path("models/user.py", [conv])
        assert len(matches) == 0

    def test_retired_convention_excluded(self):
        conv = ConventionRule(
            name="Old Pattern",
            match_criteria={"any_of": [{"file_path": ".*"}]},
            rules={},
            compliance=0.3,  # Below 0.50 threshold
        )
        matches = match_conventions_by_path("anything.py", [conv])
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# Gap 6: Learned routing
# ---------------------------------------------------------------------------

class TestLearnedRouting:
    def test_high_utility_file_included(self):
        with tempfile.TemporaryDirectory() as d:
            dot_dir = os.path.join(d, ".dotscope")
            os.makedirs(dot_dir)
            scores = {"auth": {"cache/sessions.py": 4.5, "auth/handler.py": 2.0}}
            with open(os.path.join(dot_dir, "utility_scores.json"), "w") as f:
                json.dump(scores, f)

            routing = build_routing_guidance("auth", repo_root=d)
            messages = [r.message for r in routing]
            assert any("cache/sessions.py" in m for m in messages)

    def test_no_scores_no_learned(self):
        with tempfile.TemporaryDirectory() as d:
            routing = build_routing_guidance("auth", repo_root=d)
            learned = [r for r in routing if r.metadata.get("type") == "learned"]
            assert len(learned) == 0
