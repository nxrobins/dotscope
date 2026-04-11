"""Automated, non-destructive synchronization of physical .scope files with AST topology."""

import os
import sys
from typing import List, Optional

from ..engine.discovery import find_all_scopes
from ..engine.parser import parse_scope_file, serialize_scope, ScopeConfig
from ..passes.graph_builder import build_graph, DependencyGraph
from ..paths import normalize_directory_include
from .ingest import _find_cross_module_imports, _default_excludes

def sync_scopes(root: str, scopes: Optional[List[str]] = None) -> int:
    """
    Synchronize the structural boundaries of .scope files against the current AST topology.
    Prunes dead imports natively, but honors # keep or # manual directives on specific items.
    """
    all_scope_paths = find_all_scopes(root)
    if scopes:
        # Filter to only requested scopes
        filtered = []
        for sf in all_scope_paths:
            dir_name = os.path.basename(os.path.dirname(sf))
            if dir_name in scopes:
                filtered.append(sf)
        all_scope_paths = filtered

    if not all_scope_paths:
        print("No .scope files found to sync.")
        return 0

    print(f"Building full AST topology for {len(all_scope_paths)} scope boundary target(s)...")
    graph = build_graph(root)
    
    modified_count = 0

    for scope_path in all_scope_paths:
        try:
            config = parse_scope_file(scope_path)
        except Exception as e:
            print(f"ERROR: Failed to parse {scope_path}: {e}", file=sys.stderr)
            continue

        module_directory = os.path.relpath(os.path.dirname(scope_path), root)
        if module_directory == ".":
            module_directory = ""
            
        directory_prefix = normalize_directory_include(module_directory) if module_directory else "./"

        # Find our module boundary in the graph
        target_module = None
        for mod in graph.modules:
            if mod.directory == module_directory or mod.directory == module_directory.rstrip("/\\"):
                target_module = mod
                break

        if not target_module:
            print(f"WARN: Could not locate graph cluster for {module_directory}", file=sys.stderr)
            continue

        # --- Recompute AST Includes ---
        new_includes = []
        if directory_prefix != "./":
            new_includes.append(directory_prefix)

        for dep in target_module.external_deps:
            dep_dir = os.path.join(root, dep)
            if os.path.isdir(dep_dir):
                imported_files = _find_cross_module_imports(target_module, dep, graph)
                for imp_file in imported_files:
                    if imp_file not in new_includes:
                        new_includes.append(imp_file)

        # --- Recompute AST Excludes ---
        new_excludes = _default_excludes(module_directory, target_module.files)

        # Merge Phase: Protect the manual/keep directives
        merged_includes = list(new_includes)
        for old_inc in config.includes:
            if "# keep" in old_inc.lower() or "# manual" in old_inc.lower():
                if old_inc not in merged_includes:
                    merged_includes.append(old_inc)
                    
        # Apply the merged topology directly to the config object (context fields are safe!)
        original_includes = list(config.includes)
        config.includes = sorted(merged_includes)
        config.excludes = new_excludes

        # Calculate Diff strings for output logs
        added = set(config.includes) - set(original_includes)
        removed = set(original_includes) - set(config.includes)
        
        if not added and not removed:
            print(f"  [OK] {module_directory} is perfectly synced.")
            continue
            
        # Serialize and write
        try:
            new_yaml = serialize_scope(config)
            with open(scope_path, "w", encoding="utf-8") as f:
                f.write(new_yaml)
            modified_count += 1
            print(f"  [SYNCED] {module_directory}")
            for a in added:
                print(f"      + {a}")
            for r in removed:
                print(f"      - {r}")
        except Exception as e:
            print(f"ERROR: Failed to save synced data to {scope_path}: {e}", file=sys.stderr)

    return modified_count
