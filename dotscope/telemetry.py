"""Federated Intelligence Model: Telemetry & Fingerprinting Engine.

Opt-in telemetry that ships *purely structural* metadata and success metrics
to the global dotscope Pro network. Zero source code leaves the machine.
"""

import hashlib
import json
import os
import random
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, List

from .models.core import DependencyGraph
from .models.state import SessionStats

_PENDING_PAYLOADS = []
PRO_API_BASE = "http://localhost:8000/api/v1"

def _get_api_token() -> str:
    """Retrieve the globally provisioned API key or environment fallback."""
    token = os.environ.get("DOTSCOPE_API_KEY", "")
    if token:
        return token
        
    from pathlib import Path
    cred_path = Path.home() / ".dotscope" / "credentials"
    if cred_path.exists():
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("token", "")
        except Exception:
            pass
    return ""


def fingerprint_repo(root: str) -> Dict[str, Any]:
    """Detect Framework patterns and languages without reading code."""
    fingerprint = {
        "frameworks": [],
        "languages": [],
        "package_managers": []
    }
    
    if os.path.exists(os.path.join(root, "pyproject.toml")) or os.path.exists(os.path.join(root, "requirements.txt")):
        fingerprint["languages"].append("python")
        fingerprint["package_managers"].append("pip")
        
    if os.path.exists(os.path.join(root, "package.json")):
        fingerprint["languages"].append("javascript")
        if os.path.exists(os.path.join(root, "tsconfig.json")):
            fingerprint["languages"].append("typescript")
        fingerprint["package_managers"].append("npm")
        
        if os.path.exists(os.path.join(root, "next.config.js")) or os.path.exists(os.path.join(root, "next.config.mjs")):
            fingerprint["frameworks"].append("nextjs")
            
    if os.path.exists(os.path.join(root, "manage.py")):
        fingerprint["frameworks"].append("django")
        
    return fingerprint


def anonymize_graph(graph: DependencyGraph) -> Dict[str, Any]:
    """Transform the dependency graph into a mathematical structural shape."""
    if not graph.files:
        return {"nodes": 0, "edges_count": 0, "edges": [], "modules_count": 0, "module_cohesions_sample": [], "max_in_degree": 0, "max_out_degree": 0}

    # Map paths to anonymous integer IDs
    paths = sorted(graph.files.keys())
    # Shuffle to prevent isomorphism timing correlations across syncs
    shuffled_ids = list(range(len(paths)))
    random.shuffle(shuffled_ids)
    
    node_map = {}
    for idx, path in enumerate(paths):
        node_map[path] = shuffled_ids[idx]

    edges = []
    module_cohesions = []
    
    for path, node in graph.files.items():
        src_id = node_map[path]
        for imp in node.imports:
            if imp in node_map:
                edges.append((src_id, node_map[imp]))
                
    for mod in graph.modules:
        module_cohesions.append(round(mod.cohesion, 2))

    return {
        "nodes": len(node_map),
        "edges_count": len(edges),
        "edges": edges, 
        "modules_count": len(graph.modules),
        "module_cohesions_sample": module_cohesions[:10],
        "max_in_degree": max((len(n.imported_by) for n in graph.files.values()), default=0),
        "max_out_degree": max((len(n.imports) for n in graph.files.values()), default=0)
    }


def record_session(stats: SessionStats, root: str) -> None:
    """Store structural metadata in memory until a sync occurs."""
    global _PENDING_PAYLOADS
    if not stats.scopes_resolved:
        return
        
    reduction_pct = 0.0
    if stats.tokens_available > 0:
        reduction_pct = round((1 - stats.tokens_served / stats.tokens_available) * 100, 1)

    payload = {
        "event_type": "session_completed",
        "timestamp": int(time.time() / 3600) * 3600,
        "fingerprint": fingerprint_repo(root),
        "client_identifier": stats.client_identifier,
        "session_stats": {
            "scopes_resolved": stats.scopes_resolved,
            "unique_scopes_count": len(stats.unique_scopes),
            "tokens_served": stats.tokens_served,
            "tokens_available": stats.tokens_available,
            "reduction_pct": reduction_pct,
            "attribution_hints_served": stats.attribution_hints_served,
            "health_warnings_surfaced": stats.health_warnings_surfaced,
            "duration_s": 0.0,
            "constraint_categories": {}
        }
    }
    
    constraint_categories = {}
    for c in stats.constraints_served:
        cat = c.get("category", "unknown")
        constraint_categories[cat] = constraint_categories.get(cat, 0) + 1
        
    payload["session_stats"]["constraint_categories"] = constraint_categories

    _PENDING_PAYLOADS.append(payload)


def _post_fail_open(payload: dict, endpoint: str):
    """Zero-dependency HTTP POST with strict synchronous timeout."""
    token = _get_api_token()
    if not token:
        return  # Silently fail-open if not authenticated for background pushes
        
    try:
        req = urllib.request.Request(
            endpoint, 
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
            method='POST'
        )
        # 1.5s timeout: enough for local or fast cloud, drops otherwise
        with urllib.request.urlopen(req, timeout=1.5):
            pass 
    except Exception:
        # Silently fail-open (swallow timeouts, DNS errors, offline errors)
        pass


def sync(root: str) -> None:
    """Synchronously pushes pending items in the shutdown sequence."""
    global _PENDING_PAYLOADS
    
    if not _PENDING_PAYLOADS:
        return
        
    # Drain the queue
    payloads_to_send = list(_PENDING_PAYLOADS)
    _PENDING_PAYLOADS.clear()
    
    for payload in payloads_to_send:
        _post_fail_open(payload, f"{PRO_API_BASE}/telemetry")


def get_templates(fingerprint: Dict[str, Any], topology: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Retrieve dynamic topological directives from dotscope Pro."""
    url = f"{PRO_API_BASE}/templates/compile"
        
    token = _get_api_token()
    if not token:
        import sys
        print("dotscope: No Pro token found in ~/.dotscope/credentials, falling back to local ingestion.", file=sys.stderr)
        return []
        
    try:
        payload = {
            "fingerprint": fingerprint,
            "graph_topology": topology
        }
        data_encoded = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data_encoded, method='POST', headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        })
        # Strict 2.0s timeout to prevent cold-start hanging
        with urllib.request.urlopen(req, timeout=2.0) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except Exception:
        # Silent fail-open fallback to local discovery if network is down
        return []
