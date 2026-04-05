import argparse
import os
import sys

def _cmd_validate(args):
    from ..paths.repo import find_repo_root
    from ..discovery import find_all_scopes
    from ..parser import parse_scope_file

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    scope_files = find_all_scopes(root)
    if not scope_files:
        print("No .scope files found.")
        return

    errors = 0
    warnings = 0

    for sf in scope_files:
        rel = os.path.relpath(sf, root)
        try:
            config = parse_scope_file(sf)
        except ValueError as e:
            print(f"ERROR  {rel}: {e}")
            errors += 1
            continue

        scope_dir = os.path.dirname(sf)

        from ..paths import path_exists, strip_inline_comment

        for inc in config.includes:
            if not path_exists(root, inc):
                print(f"ERROR  {rel}: include path not found: {inc}")
                errors += 1

        for related in config.related:
            clean = strip_inline_comment(related)
            if not path_exists(scope_dir, clean) and not path_exists(root, clean):
                    print(f"WARN   {rel}: related scope not found: {clean}")
                    warnings += 1

        if not config.description.strip():
            print(f"WARN   {rel}: empty description")
            warnings += 1

        if not config.context_str.strip():
            print(f"WARN   {rel}: no context (this is the most valuable part)")
            warnings += 1

    print(f"\nChecked {len(scope_files)} scope(s): {errors} error(s), {warnings} warning(s)")
    if errors > 0:
        sys.exit(1)

def _cmd_stats(args):
    from ..paths.repo import find_repo_root
    from ..discovery import find_all_scopes
    from ..parser import parse_scope_file
    from ..resolver import resolve
    from ..tokens import estimate_file_tokens
    from ..formatter import format_stats

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    total_files = 0
    total_tokens = 0
    skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            full = os.path.join(dirpath, f)
            total_files += 1
            total_tokens += estimate_file_tokens(full)

    # Resolve each scope
    scope_stats = []
    for sf in find_all_scopes(root):
        try:
            config = parse_scope_file(sf)
            resolved = resolve(config, follow_related=False, root=root)
            name = os.path.relpath(os.path.dirname(sf), root) + "/"
            scope_stats.append((name, len(resolved.files), resolved.token_estimate))
        except (ValueError, IOError):
            continue

    print(format_stats(scope_stats, total_files, total_tokens))

def _cmd_tree(args):
    from ..paths.repo import find_repo_root
    from ..discovery import find_all_scopes
    from ..parser import parse_scope_file
    from ..formatter import format_tree

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    scopes = []
    for sf in find_all_scopes(root):
        try:
            config = parse_scope_file(sf)
            scopes.append((sf, config))
        except (ValueError, IOError):
            scopes.append((sf, None))

    print(format_tree(scopes, root))

def _cmd_health(args):
    from ..health import full_health_report
    from ..paths.repo import find_repo_root

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    report = full_health_report(root, use_runtime=True)

    if not report.issues:
        print(f"All {report.scopes_checked} scope(s) healthy. "
              f"Coverage: {report.coverage_pct:.0f}% "
              f"({report.directories_covered}/{report.directories_total} directories)")
        return

    for issue in report.issues:
        rel = os.path.relpath(issue.scope_path, root) if issue.scope_path else "repo"
        tag = issue.severity.upper()
        print(f"{tag:5}  [{issue.category}] {rel}: {issue.message}")

    print(f"\n{report.scopes_checked} scope(s) checked, "
          f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    print(f"Coverage: {report.coverage_pct:.0f}% "
          f"({report.directories_covered}/{report.directories_total} directories)")

def _cmd_virtual(args):
    from ..paths.repo import find_repo_root
    from ..passes.graph_builder import build_graph
    from ..passes.virtual import detect_virtual_scopes, format_virtual_scopes

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    graph = build_graph(root)
    scopes = detect_virtual_scopes(graph)
    print(format_virtual_scopes(scopes, root))

def _cmd_lessons(args):
    from ..paths.repo import find_repo_root
    from ..storage.session_manager import SessionManager
    from ..lessons import generate_lessons

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    mgr = SessionManager(root)
    sessions = mgr.get_sessions(limit=200)
    observations = mgr.get_observations(limit=200)

    if not observations:
        print("No observations yet. Install the hook and make some commits first.")
        return

    lessons = generate_lessons(sessions, observations, module=args.scope)
    if not lessons:
        print(f"No lessons for scope '{args.scope}' yet.")
        return

    print(f"Lessons for {args.scope}:\n")
    for lesson in lessons:
        filled = int(lesson.confidence * 5)
        conf = "#" * filled + "." * (5 - filled)
        _safe_print(f"  [{conf}] {lesson.lesson_text}")
        _safe_print(f"         {lesson.observation}")
        print()

def _cmd_invariants(args):
    from ..paths.repo import find_repo_root
    from ..passes.graph_builder import build_graph
    from ..lessons import detect_invariants
    from ..passes.history_miner import analyze_history

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    graph = build_graph(root)
    history = analyze_history(root, max_commits=500)
    all_modules = [m.directory for m in graph.modules]

    invariants = detect_invariants(
        graph.edges, args.scope, all_modules, history.commits_analyzed
    )

    if not invariants:
        print(f"No invariants detected for scope '{args.scope}'")
        return

    high = [inv for inv in invariants if inv.confidence >= 0.8]
    low = [inv for inv in invariants if inv.confidence < 0.8]

    if high:
        print(f"Strong boundaries for {args.scope}:\n")
        for inv in high:
            print(f"  {inv.boundary}: no imports ({inv.commit_count} commits observed)")

    if low:
        print("\nWeak boundaries:\n")
        for inv in low[:5]:
            print(f"  {inv.boundary}: no imports (low confidence, {inv.commit_count} commits)")

def _cmd_rebuild(args):
    from ..paths.repo import find_repo_root
    from ..storage.session_manager import SessionManager
    from ..utility import rebuild_utility
    from ..lessons import generate_lessons, save_lessons, detect_invariants, save_invariants
    from ..passes.graph_builder import build_graph

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    mgr = SessionManager(root)
    mgr.ensure_initialized()
    sessions = mgr.get_sessions(limit=1000)
    observations = mgr.get_observations(limit=1000)
    dot_dir = mgr.dot_dir

    print("Rebuilding utility scores...", file=sys.stderr)
    scores = rebuild_utility(dot_dir, sessions, observations)
    print(f"  {len(scores)} file scores computed")

    print("Rebuilding lessons...", file=sys.stderr)
    graph = build_graph(root)
    all_modules = [m.directory for m in graph.modules]
    for mod in all_modules:
        lessons = generate_lessons(sessions, observations, module=mod)
        if lessons:
            save_lessons(dot_dir, mod, lessons)
            print(f"  {mod}: {len(lessons)} lesson(s)")

    print("Rebuilding invariants...", file=sys.stderr)
    from ..passes.history_miner import analyze_history
    history = analyze_history(root, max_commits=500)
    for mod in all_modules:
        invariants = detect_invariants(graph.edges, mod, all_modules, history.commits_analyzed)
        if invariants:
            save_invariants(dot_dir, mod, invariants)
            print(f"  {mod}: {len(invariants)} invariant(s)")

    print("Done.")

def _cmd_test_compiler(args):
    from ..paths.repo import find_repo_root
    from ..regression import load_regressions, replay_regression, format_replay_report

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    cases = load_regressions(root)
    if args.scope:
        cases = [c for c in cases if args.scope in c.scope_expr]

    if not cases:
        print("No regression cases found.")
        print("Sessions are auto-frozen after successful observations (recall >= 80%).")
        return

    results = []
    for case in cases:
        try:
            result = replay_regression(case, root)
            results.append(result)
        except Exception as e:
            print(f"  {case.id}: error: {e}", file=sys.stderr)

    print(format_replay_report(results))
    regressions = sum(1 for r in results if r.is_regression)
    if regressions:
        sys.exit(1)

def _cmd_bench(args):
    import json as json_mod
    from ..paths.repo import find_repo_root
    from ..bench import run_bench, format_bench_report

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    report = run_bench(root)

    if hasattr(args, "json_output") and args.json_output:
        from dataclasses import asdict
        print(json_mod.dumps(asdict(report), indent=2))
    else:
        print(format_bench_report(report))

def _cmd_debug(args):
    from ..paths.repo import find_repo_root
    from ..debug import debug_session, list_bad_sessions, format_debug_report

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    if hasattr(args, "list_bad") and args.list_bad:
        bad = list_bad_sessions(root)
        if not bad:
            print("No sessions with low recall found.")
            return
        for s in bad:
            gaps = ", ".join(s["gaps"][:2]) if s["gaps"] else "none"
            print(f"  {s['session_id'][:12]}  {s['scope']}  recall: {s['recall']:.0%}  gaps: {gaps}")
        return

    session_id = args.session_id
    if hasattr(args, "last") and args.last:
        bad = list_bad_sessions(root, limit=1)
        if bad:
            session_id = bad[0]["session_id"]
        else:
            print("No sessions with low recall found.")
            return

    if not session_id:
        print("Usage: dotscope debug <session_id> or dotscope debug --last")
        return

    result = debug_session(session_id, root)
    if result is None:
        print(f"Session {session_id} not found or has good recall (>= 80%).")
        return

    print(format_debug_report(result))