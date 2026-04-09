import json
import mmap
import os
import struct
import subprocess
from typing import Dict, Any, List
from collections import defaultdict

def execute_semantic_search(root: str, query: str) -> str:
    """The two-step Semantic Intercept pipeline: fast Git grep + zero-copy topology cast."""
    
    # STEP 1: The Fast Grep Pass via git grep
    try:
        cmd = [
            "git", "grep",
            "-I",          # Ignore binary
            "-E",          # Extended Regex 
            "-n",          # Line Numbers
            "--heading",   # Group by file
            "--break",     # Blank lines between files
            query
        ]
        # Ignore case by default to maximize recall for the agent
        cmd.insert(2, "-i")

        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=15)
        # 1 means no match, 0 means match. >1 is error
        if result.returncode > 1:
            return json.dumps({"error": f"Git grep crashed: {result.stderr}"})
        if not result.stdout.strip():
            return json.dumps({"results": [], "query": query, "message": "No semantic matches found."})
            
    except Exception as e:
        return json.dumps({"error": f"Search Exception: {str(e)}"})

    raw_output = result.stdout.splitlines()
    
    # Parser state machine for --heading format
    parsed_files = []
    current_file = None
    current_snippets = []
    
    for line in raw_output:
        if not line:
            if current_file and current_snippets:
                parsed_files.append({"file": current_file, "snippets": current_snippets})
                current_file = None
                current_snippets = []
        elif current_file is None:
            # It's a heading
            if os.path.exists(os.path.join(root, line.strip())):
                current_file = line.strip()
        else:
            # It's a line match: "14: fn test()"
            current_snippets.append(line.strip()[:200]) # Cap snippet length safely
            
    if current_file and current_snippets:
        parsed_files.append({"file": current_file, "snippets": current_snippets})

    # Limit to top 15 results mapped
    parsed_files = parsed_files[:15]
    if not parsed_files:
         return json.dumps({"results": [], "query": query})

    # STEP 2: The Topology Matrix Enrichment
    # We are under the MW lock - so we can read safely!
    active_buffer_id = 0
    control_mmap = os.path.join(root, ".dotscope", "control.mmap")
    
    if os.path.exists(control_mmap):
        try:
            with open(control_mmap, "r+b") as f:
                mm = mmap.mmap(f.fileno(), 4096)
                active_buffer_id = mm[0]
                mm.close()
        except:
            pass

    target_bin = "topology_A.bin" if active_buffer_id == 0 else "topology_B.bin"
    bin_path = os.path.join(root, ".dotscope", target_bin)
    manifest_path = os.path.join(root, ".dotscope", "structural_manifest.json")
    
    gravity_map = {}
    dep_map = defaultdict(list)
    
    # Try zero-copy enrichment mapping
    if os.path.exists(bin_path) and os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
                nodes = manifest.get("nodes", [])
                
            with open(bin_path, "rb") as f:
                # The file is just 3 continuous block arrays of sizes N * 4. We can stat it to find N.
                file_size = os.path.getsize(bin_path)
                N = file_size // 12  # (sources + targets + weights) = 3 arrays of u32 (4 bytes). 12 bytes per edge!
                
                mm = mmap.mmap(f.fileno(), file_size, access=mmap.ACCESS_READ)
                sources_bytes = mm[0 : N*4]
                targets_bytes = mm[N*4 : N*8]
                # weights_bytes = mm[N*8 : N*12]
                
                # Zero-copy the byte-aligned array directly into memory structs natively mapped
                sources = struct.unpack(f'<{N}I', sources_bytes)
                targets = struct.unpack(f'<{N}I', targets_bytes)
                
                in_edges = defaultdict(int)
                out_edges = defaultdict(int)
                
                for s_idx, t_idx in zip(sources, targets):
                    in_edges[t_idx] += 1
                    out_edges[s_idx] += 1
                    
                    if s_idx < len(nodes) and t_idx < len(nodes):
                        # Node T depends on Node S implicitly since S provides functionality to T. 
                        # Wait, edge weights are standard (if source imports target, source depends on target).
                        dep_map[nodes[s_idx]].append(nodes[t_idx])
                        
                for i, node in enumerate(nodes):
                    gravity = in_edges[i] + out_edges[i]
                    if gravity > 50:
                        gravity_map[node] = f"CRITICAL HUB (Connections: {gravity})"
                    elif gravity > 10:
                        gravity_map[node] = f"HIGH (Connections: {gravity})"
                    elif gravity > 3:
                        gravity_map[node] = f"MODERATE (Connections: {gravity})"
                    else:
                        gravity_map[node] = f"LOW (Connections: {gravity})"
                
                mm.close()
        except:
            pass

    # STEP 3: Return Formatting (Agent Gratification)
    final_output = []
    for p in parsed_files:
        file = p["file"]
        # Standardize slashes for dict lookup
        lookup_name = file.replace("\\", "/")
        
        result_node = {
            "file": file,
            "architectural_gravity": gravity_map.get(lookup_name, "UNKNOWN (Not in pure graph)"),
            "structural_dependencies": dep_map.get(lookup_name, [])[:10],
            "snippets": p["snippets"]
        }
        final_output.append(result_node)
        
    return json.dumps({"results": final_output}, indent=2)
