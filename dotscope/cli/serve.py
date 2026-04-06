"""Interactive Topography Server CLI for Dotscope.

Launches a local, zero-dependency HTTP server that intercepts requests 
for the WebGPU/Pretext topology app and hydrates it with real-time 
.scope bounds, network constraints, and stability telemetry.
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path


def _load_telemetry_payload(root: str) -> dict:
    """Build the monolithic physics payload for the WebGPU engine."""
    cache_dir = Path(root) / ".dotscope" / "cache"
    
    payload = {
        "nodes": [],
        "edges": [],
        "scopes": {},
        "invariants": []
    }
    
    # Safely load the static network graph
    edges_path = cache_dir / "network_edges.json"
    if edges_path.exists():
        try:
            with open(edges_path, "r", encoding="utf-8") as f:
                raw_edges = json.load(f)
                
            # Flatten into D3/Force graph format
            nodes_set = set()
            for source, targets in raw_edges.items():
                nodes_set.add(source)
                for consumer, _ in targets.items():
                    nodes_set.add(consumer)
                    payload["edges"].append({"source": source, "target": consumer})
                    
            for node in nodes_set:
                payload["nodes"].append({"id": node})
                
        except Exception as e:
            print(f"Failed to load network edges: {e}", file=sys.stderr)
            
    # Load Invariants (Implicit Contracts for Pulsing Tethers)
    invariants_path = cache_dir / "graph_invariants.json"
    if invariants_path.exists():
        try:
            with open(invariants_path, "r", encoding="utf-8") as f:
                payload["invariants"] = json.load(f)
        except Exception:
            pass

    return payload


def _get_ui_bundle_path() -> Path:
    """Locate the pre-compiled WebGPU Vite bundle."""
    # Production path: inside the python package assets/ui
    package_dir = Path(__file__).resolve().parent.parent
    assets_dir = package_dir / "assets" / "ui"
    
    # Fallback to source directory for dev mode
    if not assets_dir.exists():
        dev_dir = package_dir.parent / "ui" 
        if (dev_dir / "index.html").exists():
            return dev_dir
    
    return assets_dir


def _cmd_serve(args):
    """Launch the interactive topography server."""
    root = os.getcwd()
    
    # 1. Prepare Telemetry Payload
    payload = _load_telemetry_payload(root)
    json_payload = json.dumps(payload)
    
    ui_dir = _get_ui_bundle_path()
    index_path = ui_dir / "index.html"
    
    if not index_path.exists():
        print(f"Error: UI bundle not found at {ui_dir}. Have you run 'npm run build'?", file=sys.stderr)
        sys.exit(1)

    # Read the raw template
    with open(index_path, "r", encoding="utf-8") as f:
        html_template = f.read()

    # Hydrate the template with real-time graph data (Zero CORS, Zero Fetches)
    hydrated_html = html_template.replace(
        "'__GRAPH_DATA_PAYLOAD__'", 
        json_payload
    )

    # 2. Setup embedded request handler
    class TopographyHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ui_dir), **kwargs)

        def do_GET(self):
            if self.path == '/':
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(hydrated_html.encode("utf-8"))
            else:
                # Serve bundled assets (JS/CSS)
                super().do_GET()

        def log_message(self, format, *args):
            # Suppress default logging to keep terminal clean
            pass

    # 3. Launch the Server
    port = args.port
    Handler = TopographyHandler

    # Find open port if default is taken
    httpd = None
    while port < 8180:
        try:
            httpd = socketserver.TCPServer(("", port), Handler)
            break
        except OSError:
            port += 1
            
    if httpd is None:
        print("Error: Could not find an open port to bind.", file=sys.stderr)
        sys.exit(1)

    url = f"http://localhost:{port}"
    print(f"dotscope visualizer running at {url}")
    print("Press Ctrl+C to stop.")

    # 4. Auto-open browser
    def open_browser():
        webbrowser.open(url)
        
    threading.Timer(0.5, open_browser).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        httpd.server_close()
