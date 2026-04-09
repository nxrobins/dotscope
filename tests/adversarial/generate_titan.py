import sys
import uuid
import random
import os
import subprocess
from collections import defaultdict
import time
import networkx as nx

FILES_COUNT = 100000
COMMITS_COUNT = 50000
HUB_DEGREE = 3

def generate_barabasi_albert(n, m):
    print("Generating pure Barabasi-Albert Power Law Network...")
    g = nx.barabasi_albert_graph(n, m)
    adj = {i: [] for i in range(n)}
    for u, v in g.edges():
        adj[v].append(u)
    return adj

def execute():
    repo_dir = "titan_testing"
    os.makedirs(repo_dir, exist_ok=True)
    
    print("Generating Titan Barabasi-Albert Grid...")
    adj = generate_barabasi_albert(FILES_COUNT, HUB_DEGREE)
    file_uuids = [f"mod_{uuid.uuid4().hex[:8]}.js" for _ in range(FILES_COUNT)]
    
    print(f"Baking Edge Sub-Trees for Temporal Commits...")
    # Map sub-trees for correlated diff commits
    hubs = [i for i, v in enumerate(adj.keys()) if len(adj[i]) > 10]
    if len(hubs) == 0:
        hubs = [0]

    os.chdir(repo_dir)
    subprocess.run(["git", "init"], check=True)
    
    print("Constructing fast-import matrix stream...", flush=True)
    
    # We will pipe the protocol directly
    proc = subprocess.Popen(["git", "fast-import", "--quiet"], stdin=subprocess.PIPE)
    
    def write(s):
        proc.stdin.write(s.encode('utf-8'))
        
    def write_blob(filename, imports):
        content = ""
        for imp in imports:
            content += f"import {{ func_{imp} }} from './{file_uuids[imp]}';\n"
        content += f"export function func_{filename}() {{ return 42; }}\n"
        content_bytes = content.encode('utf-8')
        write(f"blob\nmark :{filename + 1}\ndata {len(content_bytes)}\n")
        proc.stdin.write(content_bytes)
        write("\n")
        
    start_time = time.time()
    
    # Pre-generate all blob objects for the 100k files
    for i in range(FILES_COUNT):
        write_blob(i, adj[i])
        
    # Generate commits
    mark_cnt = FILES_COUNT + 1
    
    # Initial commit introducing all files
    write(f"commit refs/heads/master\n")
    write(f"mark :{mark_cnt}\n")
    write(f"committer Titan <titan@engine.local> {int(time.time())} +0000\n")
    msg = f"Titan Genesis\n"
    write(f"data {len(msg)}\n{msg}")
    for file_idx in range(FILES_COUNT):
        write(f"M 100644 :{file_idx + 1} {file_uuids[file_idx]}\n")
    write("\n")
    
    mark_cnt += 1
    
    # Generate temporal coupling commits
    for c in range(COMMITS_COUNT):
        write(f"commit refs/heads/master\n")
        write(f"mark :{mark_cnt}\n")
        write(f"committer Titan <titan@engine.local> {int(time.time())} +0000\n")
        msg = f"Titan Epoch {c}\n"
        write(f"data {len(msg)}\n{msg}")
        write(f"from :{mark_cnt - 1}\n")
            
        # Select an explicit sub-tree based on real topological density
        hub = random.choice(hubs)
        affected = [hub] + adj[hub][:5]
        
        for file_idx in affected:
            write(f"M 100644 :{file_idx + 1} {file_uuids[file_idx]}\n")
        write("\n")
        
        mark_cnt += 1
        
    proc.stdin.flush()
    proc.stdin.close()
    proc.wait()
    fast_import_time = time.time() - start_time
    print(f"Git fast-import stream complete in {fast_import_time:.2f} seconds.")
    
    # Materialize files
    print("Materializing NVME OS boundary checkouts...", flush=True)
    checkout_start = time.time()
    subprocess.run(["git", "checkout", "master"], check=True, stdout=subprocess.DEVNULL)
    print(f"Checkout completed in {time.time() - checkout_start:.2f} seconds.")

if __name__ == "__main__":
    execute()
