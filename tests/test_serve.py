"""Tests for the interactive Topology Serve CLI bridge."""
import json
import os
from pathlib import Path

from dotscope.cli.serve import _load_telemetry_payload

def test_load_telemetry_payload(tmp_path):
    """Asserts that telemetry deserializes statically mapped physics payloads securely without dropping nested edges."""
    cache_dir = tmp_path / ".dotscope" / "cache"
    cache_dir.mkdir(parents=True)
    
    # Mock deeply nested Edge Graph
    edges_file = cache_dir / "network_edges.json"
    dummy_edges = {
        "src/moduleA.py": {
            "src/moduleB.py": 10
        },
        "src/moduleB.py": {
            "src/moduleC.py": 5,
            "src/moduleD.py": 2
        }
    }
    
    with open(edges_file, "w", encoding="utf-8") as f:
        json.dump(dummy_edges, f)
        
    # Mock Invariant definitions (Implicit contract tethers)
    invariants_file = cache_dir / "graph_invariants.json"
    dummy_invars = [
        {"source": "src/moduleA.py", "target": "src/moduleC.py", "type": "composition"}
    ]
    with open(invariants_file, "w", encoding="utf-8") as f:
        json.dump(dummy_invars, f)
        
    # Execute extraction securely over mathematical grid
    payload = _load_telemetry_payload(str(tmp_path))
    
    assert "edges" in payload
    assert "nodes" in payload
    assert "invariants" in payload

    # Expect D3 Flattening: 3 unique target edges should exist 
    # (A -> B), (B -> C), (B -> D)
    assert len(payload["edges"]) == 3
    
    # Ensure extraction successfully tracked all unique node endpoints
    nodes_ids = {n["id"] for n in payload["nodes"]}
    assert "src/moduleA.py" in nodes_ids
    assert "src/moduleB.py" in nodes_ids
    assert "src/moduleC.py" in nodes_ids
    assert "src/moduleD.py" in nodes_ids
    
    # Ensure static implicit tethers were loaded transparently
    assert len(payload["invariants"]) == 1
    assert payload["invariants"][0]["type"] == "composition"
