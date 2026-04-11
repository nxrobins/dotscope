import sys

with open(r'd:\dotscope\dotscope\storage\cache.py', 'r', encoding='utf-8') as f:
    text = f.read()

bad = '''        # Network contract edges (polyglot context)
        if hasattr(graph, "network_edges") and graph.network_edges:
            edges_data = {}
            for provider, consumers in graph.network_edges.items():
                edges_data[provider] = {}
                for consumer, endpoints in consumers.items():
                    edges_data[provider][consumer] = [
                        {
                            "method": getattr(ep, "method", ""),
                            "path": getattr(ep, "raw_path", ""),
                            "handler": getattr(ep, "handler_name", ""),
                        }
                        for ep in endpoints
                    ]
            with open(dot_dir / "network_edges.json", "w", encoding="utf-8") as f:
                json.dump(edges_data, f, indent=2)'''

good = '''        # Network contract edges (polyglot context)
        if hasattr(graph, "network_edges") and graph.network_edges:
            edges_data = {}
            for provider, consumers in graph.network_edges.items():
                edges_data[provider] = {}
                for consumer, endpoints in consumers.items():
                    edges_data[provider][consumer] = [
                        {
                            "method": getattr(ep, "method", ""),
                            "path": getattr(ep, "raw_path", ""),
                            "handler": getattr(ep, "handler_name", ""),
                        }
                        for ep in endpoints
                    ]
            with open(dot_dir / "network_edges.json", "w", encoding="utf-8") as f:
                json.dump(edges_data, f, indent=2)
        else:
            # FIX: Dynamically obliterate stale cache graphs if the current project structurally lacks Web APIs
            import os
            try:
                os.remove(dot_dir / "network_edges.json")
            except OSError:
                pass'''

if bad not in text:
    print('Failed to find replace block!')
    sys.exit(1)

text = text.replace(bad, good)
with open(r'd:\dotscope\dotscope\storage\cache.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Cache explicitly wiped!')
