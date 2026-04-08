import argparse
import os
import sys

def _cmd_ingest(args):
    from ..workflows.ingest import ingest, format_ingest_report

    root = os.path.abspath(args.dir)
    plan = ingest(
        root,
        mine_history=not args.no_history,
        absorb=not args.no_docs,
        max_commits=args.max_commits,
        dry_run=args.dry_run,
        quiet=args.quiet,
        voice_override=getattr(args, "voice", None),
    )

    report = format_ingest_report(plan)
    try:
        print(report)
    except UnicodeEncodeError:
        # Windows terminals with cp1252 — write as safe ASCII
        print(report.encode("ascii", errors="replace").decode("ascii"))

    if args.dry_run:
        print("Dry run: no files written. Remove --dry-run to write scope files.")
    else:
        # Onboarding: mark milestone + show next step + vc tip
        try:
            from ..storage.onboarding import (
                mark_milestone, next_step, version_control_tip, mark_vc_tip_shown,
            )
            mark_milestone(root, "first_ingest")
            tip = version_control_tip(mark_milestone(root, "first_ingest"))
            if tip:
                print(f"\n{tip}")
                mark_vc_tip_shown(root)
            ns = next_step(mark_milestone(root, "first_ingest"))
            if ns:
                print(f"\n{ns}")
        except Exception:
            pass

        # Environment Detection
        is_dotswarm = False
        if os.path.exists(os.path.join(root, "epic.yaml")) or os.path.exists(os.path.join(root, ".dotswarm")):
            is_dotswarm = True
        else:
            pyproject = os.path.join(root, "pyproject.toml")
            if os.path.exists(pyproject):
                try:
                    content = open(pyproject, "r", encoding="utf-8").read()
                    if "dotswarm" in content:
                        is_dotswarm = True
                except Exception:
                    pass
        
        print()
        if is_dotswarm:
            print("Dotswarm Phase 2 Plan Generated: Telemetry handoff ready. Run 'dotswarm plan' (or equivalent) to bootstrap execution.")
        else:
            print("Phase 2 Plan Generated: Read .dotscope/manifest.json for telemetry paths.")

def _cmd_bootstrap(args):
    root = os.path.abspath(args.dir)
    manifest_path = os.path.join(root, ".dotscope", "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"Error: No manifest found at {manifest_path}", file=sys.stderr)
        print("Please run `dotscope ingest` first to generate the Phase 2 handoff.", file=sys.stderr)
        sys.exit(1)
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        print(f.read())

def _cmd_impact(args):
    from ..passes.graph_builder import build_graph, transitive_dependents
    from ..paths.repo import find_repo_root

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    target = os.path.relpath(os.path.abspath(args.file), root)
    graph = build_graph(root)
    node = graph.files.get(target)

    print(f"Impact analysis for: {target}")
    print()

    if node and node.imports:
        print(f"Direct imports ({len(node.imports)}):")
        for imp in node.imports:
            _safe_print(f"  -> {imp}")

    if node and node.imported_by:
        print(f"\nDirect dependents ({len(node.imported_by)}):")
        for imp_by in node.imported_by:
            _safe_print(f"  <- {imp_by}")

    all_dependents = transitive_dependents(graph, target)
    transitive_only = all_dependents - set(node.imported_by if node else [])

    if transitive_only:
        print(f"\nTransitive dependents ({len(transitive_only)}):")
        for t in sorted(transitive_only):
            _safe_print(f"  <- <- {t}")

    affected_modules = set()
    for f in all_dependents:
        parts = f.split("/")
        if len(parts) > 1:
            affected_modules.add(parts[0])

    if affected_modules:
        print(f"\nAffected modules: {', '.join(sorted(affected_modules))}")

    total = 1 + len(all_dependents)
    risk = "LOW" if total <= 3 else ("MEDIUM" if total <= 10 else "HIGH")
    print(f"\nBlast radius: {total} file(s), risk: {risk}")

def _cmd_backtest(args):
    from ..passes.backtest import backtest_scopes, format_backtest_report
    from ..paths.repo import find_repo_root
    from ..engine.discovery import find_all_scopes
    from ..engine.parser import parse_scope_file

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    scope_files = find_all_scopes(root)
    if not scope_files:
        print("No .scope files found. Run 'dotscope ingest' first.")
        return

    configs = []
    for sf in scope_files:
        try:
            configs.append(parse_scope_file(sf))
        except (ValueError, IOError):
            continue

    report = backtest_scopes(root, configs, n_commits=args.commits)
    print(format_backtest_report(report))

def _cmd_conventions(args):
    import json as json_mod
    from ..paths.repo import find_repo_root
    root = find_repo_root(os.getcwd()) or os.getcwd()

    if args.discover:
        from ..passes.graph_builder import build_graph
        from ..passes.convention_discovery import discover_conventions
        from ..passes.convention_parser import parse_conventions
        from ..passes.convention_compliance import compute_compliance

        print("Analyzing codebase...", file=sys.stderr)
        graph = build_graph(root)
        if not graph.apis:
            print("No source files found to analyze.", file=sys.stderr)
            return

        discovered = discover_conventions(graph.apis, graph)
        if not discovered:
            print("No conventions discovered.", file=sys.stderr)
            return

        nodes = parse_conventions(graph.apis, discovered)
        for conv in discovered:
            conv.compliance = compute_compliance(conv, nodes, graph.apis)

        viable = [c for c in discovered if c.compliance >= 0.5]

        print(f"\nDiscovered {len(viable)} conventions:\n")
        for conv in viable:
            print(f'  "{conv.name}" -- {conv.description}')
            if conv.rules.get("required_methods"):
                print(f"    Required methods: {', '.join(conv.rules['required_methods'])}")
            if conv.rules.get("prohibited_imports"):
                print(f"    Prohibited imports: {', '.join(conv.rules['prohibited_imports'])}")
            print(f"    Compliance: {conv.compliance:.0%}")
            print()

        if args.accept:
            from ..workflows.intent import save_conventions
            save_conventions(root, viable)
            print(f"Accepted {len(viable)} conventions. Written to intent.yaml.")
        else:
            print("Run with --accept to persist, or edit manually in intent.yaml.")
        return

    # List existing conventions
    from ..workflows.intent import load_conventions
    conventions = load_conventions(root)

    if not conventions:
        print("No conventions defined. Run 'dotscope conventions --discover' to find patterns.")
        return

    if getattr(args, "json_output", False):
        data = [
            {
                "name": c.name,
                "source": c.source,
                "description": c.description,
                "compliance": c.compliance,
                "rules": c.rules,
            }
            for c in conventions
        ]
        print(json_mod.dumps(data, indent=2))
    else:
        print(f"{len(conventions)} conventions:\n")
        for conv in conventions:
            severity = "HOLD" if conv.compliance >= 0.80 else "NOTE" if conv.compliance >= 0.50 else "RETIRED"
            print(f"  [{severity}] {conv.name} ({conv.compliance:.0%} compliance)")
            if conv.description:
                print(f"         {conv.description}")
            print()

def _cmd_diff(args):
    import json as json_mod
    import subprocess
    from ..paths.repo import find_repo_root
    root = find_repo_root(os.getcwd()) or os.getcwd()

    # Get diff text
    if args.staged:
        result = subprocess.run(
            ["git", "diff", "--cached"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        diff_text = result.stdout
    elif args.ref:
        result = subprocess.run(
            ["git", "diff", args.ref], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        diff_text = result.stdout
    else:
        result = subprocess.run(
            ["git", "diff"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        diff_text = result.stdout

    if not diff_text:
        print("No changes to diff.")
        return

    from ..workflows.intent import load_conventions
    from ..passes.semantic_diff import semantic_diff, format_semantic_diff

    conventions = load_conventions(root)
    if not conventions:
        print("No conventions defined. Run 'dotscope conventions --discover' first.")
        return

    report = semantic_diff(diff_text, root, conventions)

    if getattr(args, "json_output", False):
        data = {
            "added": [{"name": n.name, "file": n.file_path} for n in report.added],
            "removed": [{"name": n.name, "file": n.file_path} for n in report.removed],
            "modified": [
                {"name": a.name, "file": a.file_path, "violations": a.violations}
                for _, a in report.modified
            ],
            "all_upheld": report.all_conventions_upheld,
        }
        print(json_mod.dumps(data, indent=2))
    else:
        print(format_semantic_diff(report))