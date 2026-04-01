"""Tests for swarm-ready primitives: partition, trace, merge."""

from types import SimpleNamespace

from dotscope.swarm.partition import (
    partition_search_space,
    _estimate_trace_depth,
    _merge_by_coupling,
)
from dotscope.swarm.trace import (
    resolve_trace,
    _get_npmi,
    _filter_context_for_trace,
    _split_context_sections,
)
from dotscope.swarm.merge import merge_scout_findings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_graph(files_dict):
    """Create a minimal graph-like object from {path: [imports]}."""
    files = {}
    for path, imports in files_dict.items():
        files[path] = SimpleNamespace(imports=imports)
    return SimpleNamespace(files=files)


def _make_index(scopes_dict):
    """Create a minimal ScopesIndex-like object from {name: directory}."""
    scopes = {}
    for name, directory in scopes_dict.items():
        scopes[name] = SimpleNamespace(directory=directory)
    return SimpleNamespace(scopes=scopes)


# ---------------------------------------------------------------------------
# Partition tests
# ---------------------------------------------------------------------------

class TestEstimateTraceDepth:
    def test_single_file(self):
        graph = _make_graph({"a.py": []})
        assert _estimate_trace_depth("a.py", graph) == 0

    def test_linear_chain(self):
        graph = _make_graph({
            "a.py": ["b.py"],
            "b.py": ["c.py"],
            "c.py": [],
        })
        assert _estimate_trace_depth("a.py", graph) == 2

    def test_cycle_terminates(self):
        graph = _make_graph({
            "a.py": ["b.py"],
            "b.py": ["a.py"],
        })
        depth = _estimate_trace_depth("a.py", graph)
        assert depth == 1  # visits a, then b, then stops (a already visited)


class TestMergeByCoupling:
    def test_no_contracts(self):
        groups = {"auth": [("auth/handler.py", 0.9)], "db": [("db/pool.py", 0.8)]}
        merged = _merge_by_coupling(groups, {"contracts": []})
        assert len(merged) == 2

    def test_high_coupling_merges(self):
        groups = {
            "auth": [("auth/handler.py", 0.9)],
            "db": [("db/pool.py", 0.8)],
        }
        invariants = {
            "contracts": [{
                "trigger_file": "auth/handler.py",
                "coupled_file": "db/pool.py",
                "confidence": 0.8,
            }]
        }
        merged = _merge_by_coupling(groups, invariants)
        assert len(merged) == 1  # Merged into one group

    def test_low_coupling_stays_separate(self):
        groups = {
            "auth": [("auth/handler.py", 0.9)],
            "db": [("db/pool.py", 0.8)],
        }
        invariants = {
            "contracts": [{
                "trigger_file": "auth/handler.py",
                "coupled_file": "db/pool.py",
                "confidence": 0.3,  # Below 0.6 threshold
            }]
        }
        merged = _merge_by_coupling(groups, invariants)
        assert len(merged) == 2


# ---------------------------------------------------------------------------
# Trace tests
# ---------------------------------------------------------------------------

class TestGetNpmi:
    def test_found_in_index(self):
        invariants = {"npmi_index": {"a.py": {"b.py": 0.85}}}
        assert _get_npmi("a.py", "b.py", invariants) == 0.85

    def test_found_reverse(self):
        invariants = {"npmi_index": {"b.py": {"a.py": 0.75}}}
        assert _get_npmi("a.py", "b.py", invariants) == 0.75

    def test_fallback_to_contracts(self):
        invariants = {
            "npmi_index": {},
            "contracts": [{
                "trigger_file": "a.py",
                "coupled_file": "b.py",
                "confidence": 0.9,
            }],
        }
        assert _get_npmi("a.py", "b.py", invariants) == 0.9

    def test_not_found(self):
        assert _get_npmi("a.py", "b.py", {}) == 0.0


class TestFilterContextForTrace:
    def test_keeps_relevant_sections(self):
        context = "## Contracts\nhandler.py and pool.py change together\n## Stability\nutils.py is stable"
        result = _filter_context_for_trace(context, ["handler.py"], None)
        assert "handler.py" in result
        assert "Contracts" in result

    def test_keeps_focus_match(self):
        context = "## Architecture\nMemory pool uses arena allocation\n## Testing\nUnit tests only"
        result = _filter_context_for_trace(context, ["other.py"], "memory")
        assert "arena" in result
        assert "Unit tests" not in result

    def test_empty_context(self):
        assert _filter_context_for_trace("", ["a.py"], None) == ""

    def test_contracts_always_kept(self):
        context = "## Implicit Contracts\nfiles coupled\n## Other\nunrelated"
        result = _filter_context_for_trace(context, ["unrelated.py"], None)
        assert "Contracts" in result


class TestSplitContextSections:
    def test_splits_by_headers(self):
        context = "## A\nline1\n## B\nline2\nline3"
        sections = _split_context_sections(context)
        assert len(sections) == 2
        assert sections[0][0] == "A"
        assert sections[1][0] == "B"

    def test_no_headers(self):
        context = "just some text\nmore text"
        sections = _split_context_sections(context)
        assert len(sections) == 1


class TestResolveTrace:
    def test_basic_trace(self):
        graph = _make_graph({
            "a.py": ["b.py"],
            "b.py": ["c.py"],
            "c.py": [],
        })
        result = resolve_trace(
            "a.py", max_depth=3, focus=None,
            repo_root="/tmp/fake", graph=graph, index=None, invariants={},
        )
        assert result["entry_file"] == "a.py"
        assert "a.py" in result["trace_path"]
        assert "b.py" in result["trace_path"]
        assert "c.py" in result["trace_path"]

    def test_depth_limit(self):
        graph = _make_graph({
            "a.py": ["b.py"],
            "b.py": ["c.py"],
            "c.py": ["d.py"],
            "d.py": [],
        })
        result = resolve_trace(
            "a.py", max_depth=1, focus=None,
            repo_root="/tmp/fake", graph=graph, index=None, invariants={},
        )
        assert "a.py" in result["trace_path"]
        assert "b.py" in result["trace_path"]
        assert "d.py" not in result["trace_path"]

    def test_cycle_handled(self):
        graph = _make_graph({
            "a.py": ["b.py"],
            "b.py": ["a.py"],
        })
        result = resolve_trace(
            "a.py", max_depth=5, focus=None,
            repo_root="/tmp/fake", graph=graph, index=None, invariants={},
        )
        assert len(result["trace_path"]) == 2


# ---------------------------------------------------------------------------
# Merge tests
# ---------------------------------------------------------------------------

class TestMergeScoutFindings:
    def test_convergence_detection(self):
        reports = [
            {"scout_id": 1, "flagged_files": ["db/conn.py", "db/pool.py"], "confidence": 0.9},
            {"scout_id": 2, "flagged_files": ["db/conn.py", "net/socket.py"], "confidence": 0.8},
        ]
        graph = _make_graph({"db/conn.py": [], "db/pool.py": [], "net/socket.py": []})
        result = merge_scout_findings(reports, "/tmp", graph, {})

        convergence = result["convergence_points"]
        assert len(convergence) == 1
        assert convergence[0]["file"] == "db/conn.py"
        assert sorted(convergence[0]["flagged_by"]) == [1, 2]

    def test_hidden_connections_via_contract(self):
        reports = [
            {"scout_id": 1, "flagged_files": ["a.py"], "confidence": 0.9},
            {"scout_id": 2, "flagged_files": ["b.py"], "confidence": 0.8},
        ]
        graph = _make_graph({"a.py": [], "b.py": []})
        invariants = {
            "contracts": [{
                "trigger_file": "a.py",
                "coupled_file": "b.py",
                "confidence": 0.88,
            }]
        }
        result = merge_scout_findings(reports, "/tmp", graph, invariants)
        assert len(result["hidden_connections"]) == 1
        assert result["hidden_connections"][0]["confidence"] == 0.88

    def test_hidden_connections_via_dependency(self):
        reports = [
            {"scout_id": 1, "flagged_files": ["a.py"], "confidence": 0.9},
            {"scout_id": 2, "flagged_files": ["b.py"], "confidence": 0.8},
        ]
        graph = _make_graph({"a.py": ["b.py"], "b.py": []})
        result = merge_scout_findings(reports, "/tmp", graph, {})
        connections = result["hidden_connections"]
        assert len(connections) == 1
        assert connections[0]["relation"] == "direct_dependency"

    def test_blast_radius_expansion(self):
        reports = [
            {"scout_id": 1, "flagged_files": ["a.py"], "confidence": 0.9},
        ]
        graph = _make_graph({"a.py": [], "expanded.py": []})
        invariants = {
            "npmi_index": {"a.py": {"expanded.py": 0.9}},
            "contracts": [],
        }
        result = merge_scout_findings(reports, "/tmp", graph, invariants)
        assert "expanded.py" in result["proposed_blast_radius"]
        assert "expanded.py" in result["blast_radius_by_confidence"]["low"]

    def test_empty_scout_reports(self):
        reports = [
            {"scout_id": 1, "flagged_files": [], "confidence": 0.5},
            {"scout_id": 2, "flagged_files": [], "confidence": 0.5},
        ]
        graph = _make_graph({})
        result = merge_scout_findings(reports, "/tmp", graph, {})
        assert result["convergence_points"] == []
        assert result["hidden_connections"] == []
        assert result["proposed_blast_radius"] == []

    def test_scout_agreement_tiers(self):
        reports = [
            {"scout_id": 1, "flagged_files": ["a.py", "b.py", "c.py"], "confidence": 0.9},
            {"scout_id": 2, "flagged_files": ["a.py", "b.py"], "confidence": 0.8},
            {"scout_id": 3, "flagged_files": ["a.py"], "confidence": 0.7},
        ]
        graph = _make_graph({"a.py": [], "b.py": [], "c.py": []})
        result = merge_scout_findings(reports, "/tmp", graph, {})
        assert "a.py" in result["scout_agreement"]["unanimous"]
        assert "b.py" in result["scout_agreement"]["majority"]
        assert "c.py" in result["scout_agreement"]["single"]

    def test_confidence_tiers(self):
        reports = [
            {"scout_id": 1, "flagged_files": ["high.py"], "confidence": 0.9},
            {"scout_id": 2, "flagged_files": ["high.py"], "confidence": 0.8},
            {"scout_id": 3, "flagged_files": ["medium.py"], "confidence": 0.8},
        ]
        graph = _make_graph({"high.py": [], "medium.py": []})
        result = merge_scout_findings(reports, "/tmp", graph, {})
        assert "high.py" in result["blast_radius_by_confidence"]["high"]
        assert "medium.py" in result["blast_radius_by_confidence"]["medium"]
