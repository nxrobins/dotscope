import os
import json
import struct
from unittest.mock import patch
import pytest
from dotscope.engine.search import execute_semantic_search

def test_semantic_search_zero_copy_enrichment(tmp_path):
    root = str(tmp_path)
    dotscope_dir = os.path.join(root, ".dotscope")
    os.makedirs(dotscope_dir, exist_ok=True)
    
    # 1. Mock the Subprocess Git Grep raw stdout output
    mocked_git_stdout = """libs/auth/middleware.py
12:def extract_auth()
15:    return session.get()

libs/db/connection.py
45:class ConnectionPool:
"""
    
    # 2. Mock the structural manifest JSON
    manifest = {
        "nodes": [
            "libs/auth/middleware.py",  # 0
            "libs/db/connection.py",    # 1
            "libs/user.py",             # 2
            "libs/session.py",          # 3
        ]
    }
    
    for node in manifest["nodes"]:
        node_path = os.path.join(root, node)
        os.makedirs(os.path.dirname(node_path), exist_ok=True)
        with open(node_path, "w") as f:
            f.write("# dummy")

    with open(os.path.join(dotscope_dir, "structural_manifest.json"), "w") as f:
        json.dump(manifest, f)
        
    # 3. Create active topology_A.bin with precise u32 edge maps
    # We want middleware to have 51 total connections (CRITICAL HUB)
    # We want connection.py to have 15 connections (HIGH)
    edges = []
    # Force 51 inbound edges to node 0 (middleware.py)
    for _ in range(51):
        edges.append((2, 0)) # user imports middleware
        
    # Force 15 inbound edges to node 1 (connection.py)
    for _ in range(15):
        edges.append((3, 1)) # session imports connection

    N = len(edges)
    sources = [e[0] for e in edges]
    targets = [e[1] for e in edges]
    
    sources_bytes = struct.pack(f'<{N}I', *sources)
    targets_bytes = struct.pack(f'<{N}I', *targets)
    weights_bytes = struct.pack(f'<{N}I', *[1]*N)
    
    with open(os.path.join(dotscope_dir, "topology_A.bin"), "wb") as f:
        f.write(sources_bytes)
        f.write(targets_bytes)
        f.write(weights_bytes)

    # 4. Mock the control.mmap active buffer byte
    with open(os.path.join(dotscope_dir, "control.mmap"), "wb") as f:
        # byte 0 is 0 -> topology_A.bin active
        f.write(b'\x00' * 4096)
        
    with patch('subprocess.run') as mock_run:
        # Create a mock result
        import subprocess
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=mocked_git_stdout, stderr="")
        mock_run.return_value = mock_result
        
        # Test the execution
        result_str = execute_semantic_search(root, "def ")
        data = json.loads(result_str)
        
        results = data["results"]
        assert len(results) == 2, "Git Grep parser failed to split headings"
        
        # Assert middleware
        assert results[0]["file"] == "libs/auth/middleware.py"
        assert "CRITICAL HUB" in results[0]["architectural_gravity"]
        assert len(results[0]["snippets"]) == 2
        
        # Assert connection
        assert results[1]["file"] == "libs/db/connection.py"
        assert "HIGH" in results[1]["architectural_gravity"]
        
        assert mock_run.call_count == 1
