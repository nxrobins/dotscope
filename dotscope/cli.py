"""CLI entry point for dotscope."""


import argparse
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dotscope",
        description="Directory-scoped context boundaries for AI coding agents",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")

    sub = parser.add_subparsers(dest="command")

    # --- resolve ---
    p_resolve = sub.add_parser("resolve", help="Resolve a scope expression to files")
    p_resolve.add_argument("scope", help="Scope name, path, or expression (e.g., auth+payments)")
    p_resolve.add_argument("--budget", type=int, default=None, help="Max tokens (context + files)")
    p_resolve.add_argument("--tokens", action="store_true", help="Show per-file token counts")
    p_resolve.add_argument("--json", action="store_true", help="Output as JSON")
    p_resolve.add_argument("--cursor", action="store_true", help="Output as .cursorrules format")
    p_resolve.add_argument("--no-related", action="store_true", help="Don't follow related scopes")
    p_resolve.add_argument("--task", default=None, help="Task description for relevance ranking")

    # --- context ---
    p_context = sub.add_parser("context", help="Print context for a scope")
    p_context.add_argument("scope", help="Scope name or path")
    p_context.add_argument("--section", default=None, help="Filter to a named section")

    # --- match ---
    p_match = sub.add_parser("match", help="Match a task description to scope(s)")
    p_match.add_argument("task", help="Task description string")

    # --- init ---
    p_init = sub.add_parser("init", help="Create a .scope file")
    p_init.add_argument("--scan", action="store_true", help="Auto-generate from directory analysis")
    p_init.add_argument("--dir", default=".", help="Directory to create .scope in")

    # --- validate ---
    sub.add_parser("validate", help="Check all .scope files for broken paths")

    # --- stats ---
    sub.add_parser("stats", help="Token savings report across all scopes")

    # --- tree ---
    sub.add_parser("tree", help="Visual tree of all scopes and relationships")

    # --- health ---
    sub.add_parser("health", help="Scope health: staleness, coverage, drift")

    # --- ingest ---
    p_ingest = sub.add_parser("ingest", help="Reverse-engineer .scope files from an existing codebase")
    p_ingest.add_argument("--dir", default=".", help="Repository root to ingest")
    p_ingest.add_argument("--no-history", action="store_true", help="Skip git history mining")
    p_ingest.add_argument("--no-docs", action="store_true", help="Skip doc absorption")
    p_ingest.add_argument("--dry-run", action="store_true", help="Plan only, don't write files")
    p_ingest.add_argument("--max-commits", type=int, default=500, help="Max git commits to analyze")

    # --- impact ---
    p_impact = sub.add_parser("impact", help="Predict blast radius of changes to a file")
    p_impact.add_argument("file", help="File path to analyze impact for")

    # --- backtest ---
    p_backtest = sub.add_parser("backtest", help="Validate scopes against git history")
    p_backtest.add_argument("--commits", type=int, default=50, help="Number of commits to test against")

    # --- observe ---
    p_observe = sub.add_parser("observe", help="Record observation for a commit (called by post-commit hook)")
    p_observe.add_argument("commit", help="Commit hash to observe")

    # --- hook ---
    p_hook = sub.add_parser("hook", help="Manage post-commit hook")
    hook_sub = p_hook.add_subparsers(dest="hook_action")
    hook_sub.add_parser("install", help="Install post-commit observer hook")
    hook_sub.add_parser("uninstall", help="Remove post-commit observer hook")
    hook_sub.add_parser("status", help="Check if hook is installed")

    # --- utility ---
    p_utility = sub.add_parser("utility", help="Show utility scores for a scope")
    p_utility.add_argument("scope", help="Scope name")

    # --- virtual ---
    sub.add_parser("virtual", help="Detect and show virtual (cross-cutting) scopes")

    # --- lessons ---
    p_lessons = sub.add_parser("lessons", help="Show lessons for a scope")
    p_lessons.add_argument("scope", help="Scope name")

    # --- invariants ---
    p_invariants = sub.add_parser("invariants", help="Show observed invariants for a scope")
    p_invariants.add_argument("scope", help="Scope name")

    # --- rebuild ---
    sub.add_parser("rebuild", help="Rebuild derived state from event logs")

    # --- check ---
    p_check = sub.add_parser("check", help="Validate a diff against codebase rules")
    p_check.add_argument("--diff", default=None, help="Path to diff file (default: staged changes)")
    p_check.add_argument("--session", default=None, help="Session ID for boundary checking")
    p_check.add_argument("--acknowledge", action="append", default=[], help="Acknowledge a hold by ID")
    p_check.add_argument("--backtest", action="store_true", help="Replay recent commits against checks")
    p_check.add_argument("--commits", type=int, default=10, help="Commits to replay in backtest mode")
    p_check.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    # --- intent ---
    p_intent = sub.add_parser("intent", help="Manage architectural intents")
    intent_sub = p_intent.add_subparsers(dest="intent_action")
    p_intent_add = intent_sub.add_parser("add", help="Add an architectural intent")
    p_intent_add.add_argument("directive", choices=["decouple", "deprecate", "freeze", "consolidate"])
    p_intent_add.add_argument("targets", nargs="+", help="Modules or files")
    p_intent_add.add_argument("--reason", default="", help="Why this intent exists")
    p_intent_add.add_argument("--replacement", default=None, help="Replacement (for deprecate)")
    p_intent_add.add_argument("--target", default=None, help="Consolidation target")
    p_intent_list = intent_sub.add_parser("list", help="List all intents")
    p_intent_rm = intent_sub.add_parser("remove", help="Remove an intent by ID")
    p_intent_rm.add_argument("id", help="Intent ID to remove")

    # --- test-compiler ---
    p_tc = sub.add_parser("test-compiler", help="Replay frozen sessions as regression tests")
    p_tc.add_argument("--scope", default=None, help="Filter to a specific scope")

    # --- bench ---
    p_bench = sub.add_parser("bench", help="Performance and accuracy benchmarks")
    p_bench.add_argument("--json", dest="json_output", action="store_true", help="JSON output")

    # --- debug ---
    p_debug = sub.add_parser("debug", help="Bisect a bad session to find root cause")
    p_debug.add_argument("session_id", nargs="?", default=None, help="Session ID to debug")
    p_debug.add_argument("--last", action="store_true", help="Debug most recent bad session")
    p_debug.add_argument("--list", dest="list_bad", action="store_true", help="List bad sessions")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    try:
        handler = {
            "resolve": _cmd_resolve,
            "context": _cmd_context,
            "match": _cmd_match,
            "init": _cmd_init,
            "validate": _cmd_validate,
            "stats": _cmd_stats,
            "tree": _cmd_tree,
            "health": _cmd_health,
            "ingest": _cmd_ingest,
            "impact": _cmd_impact,
            "backtest": _cmd_backtest,
            "observe": _cmd_observe,
            "hook": _cmd_hook,
            "utility": _cmd_utility,
            "virtual": _cmd_virtual,
            "lessons": _cmd_lessons,
            "invariants": _cmd_invariants,
            "rebuild": _cmd_rebuild,
            "check": _cmd_check,
            "intent": _cmd_intent,
            "test-compiler": _cmd_test_compiler,
            "bench": _cmd_bench,
            "debug": _cmd_debug,
        }[args.command]
        handler(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_resolve(args):
    from .composer import compose
    from .budget import apply_budget
    from .discovery import find_repo_root
    from .formatter import format_resolved

    root = find_repo_root()
    follow_related = not args.no_related

    resolved = compose(args.scope, root=root, follow_related=follow_related)

    if args.budget:
        resolved = apply_budget(resolved, args.budget, task=args.task)

    fmt = "json" if args.json else ("cursor" if args.cursor else "plain")
    print(format_resolved(resolved, fmt=fmt, root=root, show_tokens=args.tokens))


def _cmd_context(args):
    from .discovery import find_scope, find_repo_root
    from .context import query_context

    root = find_repo_root()
    config = find_scope(args.scope, root)
    if config is None:
        raise ValueError(f"Scope not found: {args.scope}")

    result = query_context(config.context, args.section)
    if result:
        print(result)
    else:
        section_msg = f" (section: {args.section})" if args.section else ""
        print(f"No context found for scope '{args.scope}'{section_msg}", file=sys.stderr)


def _cmd_match(args):
    from .matcher import match_task
    from .discovery import find_repo_root, load_index, find_all_scopes
    from .parser import parse_scope_file

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    index = load_index(root)
    scope_files = find_all_scopes(root)

    # Build scope list for matching
    scopes = []
    if index:
        for name, entry in index.scopes.items():
            scopes.append((name, entry.keywords, entry.description or ""))
    else:
        for sf in scope_files:
            try:
                config = parse_scope_file(sf)
                name = os.path.relpath(os.path.dirname(sf), root)
                scopes.append((name, config.tags, config.description))
            except (ValueError, IOError):
                continue

    matches = match_task(args.task, scopes)

    if not matches:
        print("No matching scopes found.", file=sys.stderr)
        return

    for name, score in matches:
        print(f"Matched: {name} (confidence: {score:.2f})")


def _cmd_init(args):
    from .scanner import scan_directory
    from .parser import serialize_scope

    target_dir = os.path.abspath(args.dir)
    scope_path = os.path.join(target_dir, ".scope")

    if os.path.exists(scope_path):
        print(f".scope already exists at {scope_path}", file=sys.stderr)
        sys.exit(1)

    if args.scan:
        config = scan_directory(target_dir)
        content = serialize_scope(config)
    else:
        # Interactive: create a minimal template
        name = os.path.basename(target_dir)
        content = f"""description: {name}
includes:
  - {name}/
excludes:
  - {name}/tests/fixtures/
  - {name}/__pycache__/
context: |
  # TODO: Add architectural context here.
  # What invariants does this module maintain?
  # What gotchas should an agent know about?
  # What conventions does it follow?
"""

    with open(scope_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Created {scope_path}")
    if not args.scan:
        print("Edit the context field — that's the part that can't be automated.")


def _cmd_validate(args):
    from .discovery import find_repo_root, find_all_scopes
    from .parser import parse_scope_file

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

        from .paths import path_exists, strip_inline_comment

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
    from .discovery import find_repo_root, find_all_scopes
    from .parser import parse_scope_file
    from .resolver import resolve
    from .tokens import estimate_file_tokens
    from .formatter import format_stats

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
    from .discovery import find_repo_root, find_all_scopes
    from .parser import parse_scope_file
    from .formatter import format_tree

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
    from .health import full_health_report
    from .discovery import find_repo_root

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    report = full_health_report(root)

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


def _cmd_ingest(args):
    from .ingest import ingest, format_ingest_report

    root = os.path.abspath(args.dir)
    plan = ingest(
        root,
        mine_history=not args.no_history,
        absorb=not args.no_docs,
        max_commits=args.max_commits,
        dry_run=args.dry_run,
    )

    report = format_ingest_report(plan)
    try:
        print(report)
    except UnicodeEncodeError:
        # Windows terminals with cp1252 — write as safe ASCII
        print(report.encode("ascii", errors="replace").decode("ascii"))

    if args.dry_run:
        print("Dry run — no files written. Remove --dry-run to write scope files.")
    else:
        # Onboarding: mark milestone + show next step + vc tip
        try:
            from .onboarding import (
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


def _cmd_impact(args):
    from .graph import build_graph, transitive_dependents
    from .discovery import find_repo_root

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
            print(f"  → {imp}")

    if node and node.imported_by:
        print(f"\nDirect dependents ({len(node.imported_by)}):")
        for imp_by in node.imported_by:
            print(f"  ← {imp_by}")

    all_dependents = transitive_dependents(graph, target)
    transitive_only = all_dependents - set(node.imported_by if node else [])

    if transitive_only:
        print(f"\nTransitive dependents ({len(transitive_only)}):")
        for t in sorted(transitive_only):
            print(f"  ← ← {t}")

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


def _cmd_observe(args):
    from pathlib import Path
    from .sessions import SessionManager
    from .discovery import find_repo_root
    from .visibility import format_observation_delta

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    mgr = SessionManager(root)
    obs = mgr.record_observation(args.commit)

    if obs:
        # Find the session to get scope_expr
        sessions = mgr.get_sessions(limit=50)
        scope_expr = "unknown"
        for s in sessions:
            if s.session_id == obs.session_id:
                scope_expr = s.scope_expr
                break

        # Onboarding: mark first observation + increment counter
        try:
            from .onboarding import mark_milestone, increment_counter
            mark_milestone(root, "first_observation")
            increment_counter(root, "observations_recorded")
        except Exception:
            pass

        delta = format_observation_delta(obs, scope_expr)
        try:
            print(delta, file=sys.stderr)
        except UnicodeEncodeError:
            print(delta.encode("ascii", errors="replace").decode("ascii"),
                  file=sys.stderr)

        # Update utility scores after observation
        try:
            from .utility import compute_utility_scores, save_utility_scores
            all_sessions = mgr.get_sessions(limit=500)
            all_obs = mgr.get_observations(limit=500)
            scores = compute_utility_scores(all_sessions, all_obs)
            save_utility_scores(Path(root) / ".dotscope", scores)
        except Exception:
            pass  # Utility update is best-effort

        # Near-miss detection using structured warning pairs
        try:
            import subprocess
            from .near_miss import (
                detect_near_misses as detect_nms,
                store_near_misses, load_session_scopes,
            )
            from .discovery import find_scope
            from .parser import parse_scope_file

            # Get scopes from session or current observation
            scope_name = scope_expr.split("+")[0].split("-")[0].split("@")[0]
            session_scopes = load_session_scopes(root) or [scope_name]

            # Build context map for all session scopes
            scope_contexts = {}
            for sn in session_scopes:
                cfg_path = find_scope(sn, root=root)
                if cfg_path:
                    cfg = parse_scope_file(cfg_path)
                    scope_contexts[sn] = cfg.context_str

            if scope_contexts:
                diff_result = subprocess.run(
                    ["git", "diff", obs.commit_hash + "~1", obs.commit_hash],
                    cwd=root, capture_output=True, text=True, timeout=5,
                )
                if diff_result.returncode == 0 and diff_result.stdout:
                    nms = detect_nms(diff_result.stdout, scope_contexts)
                    for nm in nms:
                        print(
                            f"\ndotscope: near-miss detected\n"
                            f"  {nm.event}\n"
                            f"  Scope context: \"{nm.context_used}\"\n"
                            f"  {nm.potential_impact}",
                            file=sys.stderr,
                        )
                    if nms:
                        store_near_misses(root, nms)
        except Exception:
                pass  # Near-miss detection is best-effort
    else:
        # No session matched — check if any scopes exist
        try:
            from .discovery import load_index
            idx = load_index(root)
            if idx:
                print(
                    "dotscope: observation recorded\n"
                    "  Changed files don't match any recent session\n"
                    "  This is normal for work done outside agent sessions",
                    file=sys.stderr,
                )
            else:
                print(
                    "dotscope: observation recorded\n"
                    "  No .scopes index found"
                    " -- consider running `dotscope ingest .`",
                    file=sys.stderr,
                )
        except Exception:
            print(f"No matching session for commit {args.commit[:8]}",
                  file=sys.stderr)


def _cmd_hook(args):
    from .hooks import install_hook, uninstall_hook, is_hook_installed
    from .discovery import find_repo_root

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    if args.hook_action == "install":
        path = install_hook(root)
        print(f"Hook installed: {path}")
    elif args.hook_action == "uninstall":
        removed = uninstall_hook(root)
        print("Hook removed." if removed else "No hook found.")
    elif args.hook_action == "status":
        installed = is_hook_installed(root)
        print(f"Hook: {'installed' if installed else 'not installed'}")
    else:
        print("Usage: dotscope hook {install|uninstall|status}")


def _cmd_backtest(args):
    from .backtest import backtest_scopes, format_backtest_report
    from .discovery import find_repo_root, find_all_scopes
    from .parser import parse_scope_file

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


def _cmd_utility(args):
    from .discovery import find_repo_root
    from .sessions import SessionManager
    from .utility import compute_utility_scores

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    mgr = SessionManager(root)
    sessions = mgr.get_sessions(limit=200)
    observations = mgr.get_observations(limit=200)

    if not observations:
        print("No observations yet. Install the hook and make some commits first.")
        print("  dotscope hook install")
        return

    scores = compute_utility_scores(sessions, observations)
    # Filter to scope
    scope_prefix = args.scope + "/"
    relevant = {k: v for k, v in scores.items() if scope_prefix in k or args.scope in k}

    if not relevant:
        print(f"No utility data for scope '{args.scope}'")
        return

    print(f"Utility scores for {args.scope} ({len(relevant)} files):\n")
    for path, score in sorted(relevant.items(), key=lambda x: -x[1].utility_ratio):
        bar = "█" * int(score.utility_ratio * 10) + "░" * (10 - int(score.utility_ratio * 10))
        print(f"  {os.path.basename(path)}: {bar} {score.utility_ratio:.0%} "
              f"({score.touch_count}/{score.resolve_count})")


def _cmd_virtual(args):
    from .discovery import find_repo_root
    from .graph import build_graph
    from .virtual import detect_virtual_scopes, format_virtual_scopes

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    graph = build_graph(root)
    scopes = detect_virtual_scopes(graph)
    print(format_virtual_scopes(scopes, root))


def _cmd_lessons(args):
    from .discovery import find_repo_root
    from .sessions import SessionManager
    from .lessons import generate_lessons

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
        conf = "█" * int(lesson.confidence * 5) + "░" * (5 - int(lesson.confidence * 5))
        print(f"  [{conf}] {lesson.lesson_text}")
        print(f"         {lesson.observation}")
        print()


def _cmd_invariants(args):
    from .discovery import find_repo_root
    from .graph import build_graph
    from .lessons import detect_invariants
    from .history import analyze_history

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
    from .discovery import find_repo_root
    from .sessions import SessionManager
    from .utility import rebuild_utility
    from .lessons import generate_lessons, save_lessons, detect_invariants, save_invariants
    from .graph import build_graph

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
    from .history import analyze_history
    history = analyze_history(root, max_commits=500)
    for mod in all_modules:
        invariants = detect_invariants(graph.edges, mod, all_modules, history.commits_analyzed)
        if invariants:
            save_invariants(dot_dir, mod, invariants)
            print(f"  {mod}: {len(invariants)} invariant(s)")

    print("Done.")


def _cmd_check(args):
    import json as json_mod
    from .discovery import find_repo_root
    from .check.checker import check_diff, check_staged, format_terminal

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    if args.backtest:
        _cmd_check_backtest(root, args.commits, args.json_output)
        return

    if args.diff:
        with open(args.diff, "r", encoding="utf-8") as f:
            diff_text = f.read()
        report = check_diff(
            diff_text, root,
            session_id=args.session,
            acknowledge_ids=args.acknowledge,
        )
    else:
        report = check_staged(root, session_id=args.session)

    if args.json_output:
        data = {
            "passed": report.passed,
            "holds": [
                {
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "message": r.message,
                    "file": r.file,
                    "suggestion": r.suggestion,
                    "acknowledge_id": r.acknowledge_id,
                    "proposed_fix": {
                        "file": r.proposed_fix.file,
                        "reason": r.proposed_fix.reason,
                        "predicted_sections": r.proposed_fix.predicted_sections,
                        "confidence": r.proposed_fix.confidence,
                    } if r.proposed_fix else None,
                }
                for r in report.holds
            ],
            "notes": [
                {
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "message": r.message,
                    "file": r.file,
                }
                for r in report.notes
            ],
            "files_checked": report.files_checked,
        }
        print(json_mod.dumps(data, indent=2))
    else:
        output = format_terminal(report)
        try:
            print(output)
        except UnicodeEncodeError:
            print(output.encode("ascii", errors="replace").decode("ascii"))

    if not report.passed:
        sys.exit(1)


def _cmd_check_backtest(root, n_commits, json_output):
    """Replay recent commits against checks to validate enforcement."""
    import json as json_mod
    import subprocess
    from .check.checker import check_diff

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n_commits}", "--pretty=format:%H|%s"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print("Could not read git log", file=sys.stderr)
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("git not available", file=sys.stderr)
        return

    commits = []
    for line in result.stdout.strip().splitlines():
        if "|" in line:
            h, msg = line.split("|", 1)
            commits.append((h.strip(), msg.strip()))

    if not commits:
        print("No commits found")
        return

    print(f"dotscope: replaying last {len(commits)} commits\n")

    clean = 0
    total_holds = 0
    total_notes = 0

    for commit_hash, message in commits:
        try:
            diff_result = subprocess.run(
                ["git", "diff", commit_hash + "~1", commit_hash],
                cwd=root, capture_output=True, text=True, timeout=10,
            )
            if diff_result.returncode != 0 or not diff_result.stdout:
                continue
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        report = check_diff(diff_result.stdout, root)

        if report.passed and not report.notes:
            clean += 1
            continue

        print(f"  commit {commit_hash[:7]}  \"{message}\"")
        for r in report.holds:
            print(f"  HOLD  {r.category.value}")
            print(f"    {r.message}")
            total_holds += 1
        for r in report.notes:
            print(f"  NOTE  {r.category.value}")
            print(f"    {r.message}")
            total_notes += 1
        print()

    print(f"  {clean} commits clean, {total_holds} hold(s), {total_notes} note(s)")
    if total_holds:
        print(f"  dotscope would have caught {total_holds} issue(s) before they shipped")

    # Onboarding: mark backtest milestone + show next step
    try:
        from .onboarding import mark_milestone, next_step
        state = mark_milestone(root, "first_backtest")
        ns = next_step(state)
        if ns:
            print(f"\n{ns}")
    except Exception:
        pass


def _cmd_test_compiler(args):
    from .discovery import find_repo_root
    from .regression import load_regressions, replay_regression, format_replay_report

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
            print(f"  {case.id}: error — {e}", file=sys.stderr)

    print(format_replay_report(results))
    regressions = sum(1 for r in results if r.is_regression)
    if regressions:
        sys.exit(1)


def _cmd_bench(args):
    import json as json_mod
    from .discovery import find_repo_root
    from .bench import run_bench, format_bench_report

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
    from .discovery import find_repo_root
    from .debug import debug_session, list_bad_sessions, format_debug_report

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


def _cmd_intent(args):
    from .discovery import find_repo_root
    from .intent import load_intents, add_intent, remove_intent

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    if args.intent_action == "add":
        intent = add_intent(
            root,
            directive=args.directive,
            targets=args.targets,
            reason=args.reason,
            replacement=args.replacement,
            target=args.target,
        )
        print(f"Added intent: {intent.directive} (id: {intent.id})")

    elif args.intent_action == "list":
        intents = load_intents(root)
        if not intents:
            print("No intents defined. Use 'dotscope intent add' to declare architectural direction.")
            return
        for intent in intents:
            targets = ", ".join(intent.modules + intent.files)
            print(f"  [{intent.id}] {intent.directive} {targets}")
            if intent.reason:
                print(f"         {intent.reason}")
            print(f"         set by {intent.set_by} on {intent.set_at}")
            print()

    elif args.intent_action == "remove":
        removed = remove_intent(root, args.id)
        print("Removed." if removed else f"Intent not found: {args.id}")

    else:
        print("Usage: dotscope intent {add|list|remove}")


def _version():
    from . import __version__
    return __version__


if __name__ == "__main__":
    main()
