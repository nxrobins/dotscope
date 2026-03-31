"""CLI entry point for dotscope."""


import argparse
import os
import sys


def _safe_print(text, **kwargs):
    """Print with ASCII fallback for Windows cp1252 terminals."""
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"), **kwargs)


def main(argv=None):
    from .textio import consume_decode_warnings

    consume_decode_warnings()

    # Intercept help before argparse touches it
    args_list = argv if argv is not None else sys.argv[1:]
    if not args_list or args_list == ["help"] or args_list == ["--help"] or args_list == ["-h"]:
        from .help import print_help
        print_help()
        return
    if len(args_list) >= 2 and args_list[1] in ("--help", "-h"):
        from .help import print_help, HELP_COMMANDS
        cmd = args_list[0]
        if cmd in HELP_COMMANDS:
            print_help(cmd)
            return
        # Fall through to argparse for unknown commands

    parser = argparse.ArgumentParser(
        prog="dotscope",
        description="Directory-scoped context boundaries for AI coding agents",
        add_help=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    parser.add_argument("-h", "--help", action="store_true", dest="show_help")

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
    p_init = sub.add_parser("init", help="One command: ingest, install hooks, configure agents")
    p_init.add_argument("path", nargs="?", default=".", help="Repository root")
    p_init.add_argument("--quiet", action="store_true", help="Suppress progress (for CI)")

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
    p_ingest.add_argument("--quiet", action="store_true", help="Suppress progress output (for CI)")
    p_ingest.add_argument("--voice", choices=["prescriptive", "adaptive"], default=None,
                          help="Override voice mode (prescriptive for new, adaptive for existing)")

    # --- voice ---
    p_voice = sub.add_parser("voice", help="View and manage code voice")
    p_voice.add_argument("--upgrade", metavar="RULE", help="Upgrade enforcement for a rule (typing, bare_excepts)")
    p_voice.add_argument("--reset", action="store_true", help="Reset voice to defaults")
    p_voice.add_argument("--json", action="store_true", help="Machine-readable output")

    # --- impact ---
    p_impact = sub.add_parser("impact", help="Predict blast radius of changes to a file")
    p_impact.add_argument("file", help="File path to analyze impact for")

    # --- backtest ---
    p_backtest = sub.add_parser("backtest", help="Validate scopes against git history")
    p_backtest.add_argument("--commits", type=int, default=50, help="Number of commits to test against")

    # --- observe ---
    p_observe = sub.add_parser("observe", help="Record observation for a commit (called by post-commit hook)")
    p_observe.add_argument("commit", help="Commit hash to observe")

    # --- incremental ---
    p_incremental = sub.add_parser("incremental", help="Incremental scope update (called by post-commit hook)")
    p_incremental.add_argument("commit", help="Commit hash")

    # --- hook ---
    p_hook = sub.add_parser("hook", help="Manage git hooks")
    hook_sub = p_hook.add_subparsers(dest="hook_action")
    hook_sub.add_parser("install", help="Install post-commit observer hook")
    hook_sub.add_parser("uninstall", help="Remove post-commit observer hook")
    hook_sub.add_parser("status", help="Check if hook is installed")
    hook_sub.add_parser("claude", help="Install Claude Code pre-commit enforcement")

    # --- refresh ---
    p_refresh = sub.add_parser("refresh", help="Manage runtime refresh queue and worker")
    refresh_sub = p_refresh.add_subparsers(dest="refresh_action")
    p_refresh_enqueue = refresh_sub.add_parser("enqueue", help="Queue runtime refresh work")
    p_refresh_enqueue.add_argument("scopes", nargs="*", help="Scope names to refresh")
    p_refresh_enqueue.add_argument("--commit", default=None, help="Classify a commit into refresh work")
    p_refresh_enqueue.add_argument("--repo", action="store_true", help="Enqueue a full repo runtime refresh")
    p_refresh_enqueue.add_argument("--reason", default="", help="Reason stored with the queued job")
    p_refresh_run = refresh_sub.add_parser("run", help="Run queued refresh work")
    p_refresh_run.add_argument("--drain", action="store_true", help="Drain the entire queue")
    refresh_sub.add_parser("status", help="Show refresh worker and queue status")

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

    # --- conventions ---
    p_conv = sub.add_parser("conventions", help="List or discover conventions")
    p_conv.add_argument("--discover", action="store_true", help="Discover conventions from codebase")
    p_conv.add_argument("--accept", action="store_true", help="Accept discovered conventions")
    p_conv.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    # --- diff ---
    p_diff = sub.add_parser("diff", help="Semantic diff against conventions")
    p_diff.add_argument("ref", nargs="?", default=None, help="Git ref to diff against")
    p_diff.add_argument("--staged", action="store_true", help="Diff staged changes")
    p_diff.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

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

    if args.command is None or getattr(args, "show_help", False):
        from .help import print_help
        print_help()
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
            "incremental": _cmd_incremental,
            "hook": _cmd_hook,
            "refresh": _cmd_refresh,
            "utility": _cmd_utility,
            "virtual": _cmd_virtual,
            "lessons": _cmd_lessons,
            "invariants": _cmd_invariants,
            "rebuild": _cmd_rebuild,
            "check": _cmd_check,
            "intent": _cmd_intent,
            "conventions": _cmd_conventions,
            "diff": _cmd_diff,
            "voice": _cmd_voice,
            "test-compiler": _cmd_test_compiler,
            "bench": _cmd_bench,
            "debug": _cmd_debug,
        }[args.command]
        handler(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        warnings = consume_decode_warnings()
        if warnings:
            count = len(warnings)
            noun = "file" if count == 1 else "files"
            _safe_print(
                f"dotscope: decoded {count} repo {noun} with replacement; "
                "run `dotscope health` for details",
                file=sys.stderr,
            )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_resolve(args):
    from .composer import compose
    from .passes.budget_allocator import apply_budget
    from .discovery import find_repo_root
    from .formatter import format_resolved
    from .refresh import ensure_resolution_freshness

    root = find_repo_root()
    follow_related = not args.no_related
    if root is not None:
        ensure_resolution_freshness(root, args.scope)

    resolved = compose(args.scope, root=root, follow_related=follow_related)

    if args.budget:
        resolved = apply_budget(resolved, args.budget, task=args.task)

    fmt = "json" if args.json else ("cursor" if args.cursor else "plain")
    print(format_resolved(resolved, fmt=fmt, root=root, show_tokens=args.tokens))


def _cmd_context(args):
    from .discovery import find_repo_root, find_resolution_scope
    from .context import query_context
    from .refresh import ensure_resolution_freshness

    root = find_repo_root()
    if root is not None:
        ensure_resolution_freshness(root, args.scope)
    config = find_resolution_scope(args.scope, root)
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
    from .discovery import find_repo_root, load_resolution_index, load_resolution_scopes

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    index = load_resolution_index(root)

    # Build scope list for matching
    scopes = []
    if index:
        for name, entry in index.scopes.items():
            scopes.append((name, entry.keywords, entry.description or ""))
    else:
        for logical_path, config, _source in load_resolution_scopes(root):
            name = os.path.dirname(logical_path) or "."
            scopes.append((name, config.tags, config.description))

    matches = match_task(args.task, scopes)

    if not matches:
        print("No matching scopes found.", file=sys.stderr)
        return

    for name, score in matches:
        print(f"Matched: {name} (confidence: {score:.2f})")


def _cmd_init(args):
    """One command: ingest, hooks, MCP config, counterfactual demo."""
    root = os.path.abspath(getattr(args, "path", None) or ".")
    quiet = getattr(args, "quiet", False)

    # 1. Ingest
    from .ingest import ingest
    result = ingest(root, quiet=quiet)

    # 2. Install hooks
    try:
        from .storage.git_hooks import install_hook
        install_hook(root)
        if not quiet:
            print("dotscope: hooks installed", file=sys.stderr)
    except Exception as e:
        print(f"dotscope: hook install failed: {e}", file=sys.stderr)

    # 3. Auto-configure MCP for detected IDEs
    try:
        from .storage.mcp_config import configure_mcp
        configured = configure_mcp(root)
        if configured and not quiet:
            print(f"dotscope: MCP configured for {', '.join(configured)}", file=sys.stderr)
    except Exception as e:
        print(f"dotscope: MCP config failed: {e}", file=sys.stderr)

    # 4. Write AGENT_INSTRUCTIONS.md
    try:
        _write_agent_instructions(root, quiet)
    except Exception as e:
        if not quiet:
            print(f"dotscope: agent instructions failed: {e}", file=sys.stderr)

    # 5. Backtest as counterfactual demo
    if not quiet:
        try:
            from .passes.backtest import backtest_scopes
            report = backtest_scopes(root, commits=50)
            if report and report.get("results"):
                total_violations = 0
                for scope_result in report["results"]:
                    total_violations += scope_result.get("missed_files", 0)

                # Extract stats from IngestPlan object
                stats = {
                    "scopes_written": len(result.scopes) if hasattr(result, "scopes") else 0,
                    "contracts_found": (
                        len(result.history.implicit_contracts)
                        if hasattr(result, "history") and result.history else 0
                    ),
                    "conventions_found": (
                        len(result.discovered_conventions) if hasattr(result, "discovered_conventions") else 0
                    ),
                }
                _print_counterfactual(stats, report, total_violations)
            else:
                _print_summary(result)
        except Exception:
            # Backtest may fail on repos with few commits
            _print_summary(result)


def _print_counterfactual(ingest_result, backtest, violations):
    """Format init output as a counterfactual story."""
    scopes = ingest_result.get("scopes_written", 0) if isinstance(ingest_result, dict) else 0
    contracts = ingest_result.get("contracts_found", 0) if isinstance(ingest_result, dict) else 0
    conventions = ingest_result.get("conventions_found", 0) if isinstance(ingest_result, dict) else 0

    recall = backtest.get("overall_recall", 0)

    lines = [""]
    lines.append(f"  {scopes} scopes, {contracts} contracts, {conventions} conventions, {recall:.0%} recall")
    lines.append("")

    if violations > 0:
        lines.append(f"  What dotscope would have caught in your last 50 commits:")
        lines.append(f"    {violations} files that agents would have missed")
    lines.append("")
    lines.append("  Your agents are ready.")
    lines.append("")

    print("\n".join(lines), file=sys.stderr)


def _write_agent_instructions(root: str, quiet: bool = False):
    """Write AGENT_INSTRUCTIONS.md to the target repo if it doesn't exist."""
    target = os.path.join(root, "AGENT_INSTRUCTIONS.md")
    if os.path.exists(target):
        if not quiet:
            print("dotscope: AGENT_INSTRUCTIONS.md already exists, skipping", file=sys.stderr)
        return

    # Load the template from the dotscope package
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template = os.path.join(package_dir, "AGENT_INSTRUCTIONS.md")

    if os.path.isfile(template):
        import shutil
        shutil.copy2(template, target)
    else:
        # Fallback: write a minimal version
        with open(target, "w", encoding="utf-8") as f:
            f.write("# dotscope Agent Instructions\n\n")
            f.write("Start every task with `codebase_search`. Run `dotscope_check` before every commit.\n\n")
            f.write("See https://github.com/nxrobins/dotscope for full documentation.\n")

    if not quiet:
        print("dotscope: AGENT_INSTRUCTIONS.md written", file=sys.stderr)


def _print_summary(ingest_result):
    """Fallback when backtest isn't available."""
    print("", file=sys.stderr)
    print("  Your agents are ready.", file=sys.stderr)
    print("", file=sys.stderr)


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


def _cmd_ingest(args):
    from .ingest import ingest, format_ingest_report

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
            from .storage.onboarding import (
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
    from .passes.graph_builder import build_graph, transitive_dependents
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


def _cmd_observe(args):
    from pathlib import Path
    from .storage.session_manager import SessionManager
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
            from .storage.onboarding import mark_milestone, increment_counter
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
            from .storage.near_miss import (
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


def _cmd_incremental(args):
    """Incremental scope update from a single commit."""
    import subprocess
    from .discovery import find_repo_root
    from .passes.incremental import incremental_update

    root = find_repo_root()
    if root is None:
        return

    # Get changed files from the commit
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", args.commit],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
    except Exception:
        return

    changed = []
    added = []
    deleted = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, filepath = parts[0].strip(), parts[1].strip()
        changed.append(filepath)
        if status == "A":
            added.append(filepath)
        elif status == "D":
            deleted.append(filepath)

    if changed:
        try:
            incremental_update(root, changed, added, deleted, args.commit)
        except Exception:
            pass  # Incremental update is best-effort


def _cmd_hook(args):
    from .storage.git_hooks import install_hook, uninstall_hook, hook_status
    from .discovery import find_repo_root

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    if args.hook_action == "install":
        result = install_hook(root)
        print(result)
    elif args.hook_action == "uninstall":
        removed = uninstall_hook(root)
        print("Hooks removed." if removed else "No hooks found.")
    elif args.hook_action == "status":
        print(hook_status(root))
    elif args.hook_action == "claude":
        from .storage.claude_hooks import install_claude_hook
        result = install_claude_hook(root)
        print(result)
    else:
        print("Usage: dotscope hook {install|uninstall|status|claude}")


def _cmd_refresh(args):
    from .discovery import find_repo_root
    from .refresh import (
        enqueue_commit_refresh,
        enqueue_repo_refresh,
        enqueue_scope_refresh,
        kick_refresh_worker,
        refresh_status_summary,
        run_refresh_queue,
    )

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    if args.refresh_action == "enqueue":
        job = None
        if args.commit:
            job = enqueue_commit_refresh(root, args.commit)
        elif args.repo:
            job = enqueue_repo_refresh(root, reason=args.reason)
        else:
            job = enqueue_scope_refresh(root, args.scopes, reason=args.reason)

        if job is None:
            print("No refresh work queued.")
            return

        kick_refresh_worker(root)
        targets = ", ".join(job.get("targets", [])) if job.get("targets") else "repo"
        print(f"Queued {job.get('kind')} refresh for {targets}.")
        return

    if args.refresh_action == "run":
        ran = run_refresh_queue(root, drain=args.drain)
        print("Refresh worker ran." if ran else "No refresh work run.")
        return

    if args.refresh_action == "status":
        status = refresh_status_summary(root)
        current_targets = ", ".join(status.get("current_targets", [])) or "-"
        print(f"running: {status.get('running')}")
        print(f"current_job: {status.get('current_job') or '-'}")
        print(f"current_targets: {current_targets}")
        print(f"queued_job_count: {status.get('queued_job_count', 0)}")
        if status.get("last_success_at"):
            print(f"last_success_at: {status['last_success_at']}")
        if status.get("last_error"):
            print(f"last_error: {status['last_error']}")
        return

    print("Usage: dotscope refresh {enqueue|run|status}")


def _cmd_backtest(args):
    from .passes.backtest import backtest_scopes, format_backtest_report
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
    from .storage.session_manager import SessionManager
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
        filled = int(score.utility_ratio * 10)
        bar = "#" * filled + "." * (10 - filled)
        _safe_print(f"  {os.path.basename(path)}: {bar} {score.utility_ratio:.0%} "
                    f"({score.touch_count}/{score.resolve_count})")


def _cmd_virtual(args):
    from .discovery import find_repo_root
    from .passes.graph_builder import build_graph
    from .passes.virtual import detect_virtual_scopes, format_virtual_scopes

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    graph = build_graph(root)
    scopes = detect_virtual_scopes(graph)
    print(format_virtual_scopes(scopes, root))


def _cmd_lessons(args):
    from .discovery import find_repo_root
    from .storage.session_manager import SessionManager
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
        filled = int(lesson.confidence * 5)
        conf = "#" * filled + "." * (5 - filled)
        _safe_print(f"  [{conf}] {lesson.lesson_text}")
        _safe_print(f"         {lesson.observation}")
        print()


def _cmd_invariants(args):
    from .discovery import find_repo_root
    from .passes.graph_builder import build_graph
    from .lessons import detect_invariants
    from .passes.history_miner import analyze_history

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
    from .storage.session_manager import SessionManager
    from .utility import rebuild_utility
    from .lessons import generate_lessons, save_lessons, detect_invariants, save_invariants
    from .passes.graph_builder import build_graph

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
    from .passes.history_miner import analyze_history
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
    from .passes.sentinel.checker import check_diff, check_staged, format_terminal

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
    from .passes.sentinel.checker import check_diff

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
        from .storage.onboarding import mark_milestone, next_step
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
            print(f"  {case.id}: error: {e}", file=sys.stderr)

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


def _cmd_voice(args):
    import json as json_mod
    from .discovery import find_repo_root
    from .intent import load_voice_config

    root = find_repo_root(".")
    voice = load_voice_config(root)

    if voice is None:
        print("No voice discovered. Run `dotscope ingest .` first.", file=sys.stderr)
        return

    if getattr(args, "json", False):
        print(json_mod.dumps(voice, indent=2, default=str))
        return

    if getattr(args, "upgrade", None):
        rule = args.upgrade
        enforce = voice.get("enforce", {})
        current = enforce.get(rule)
        if current is False:
            enforce[rule] = "note"
        elif current == "note":
            enforce[rule] = "hold"
        else:
            print(f"{rule}: already at highest enforcement level", file=sys.stderr)
            return

        # Save back
        from .models.intent import DiscoveredVoice
        dv = DiscoveredVoice(
            mode=voice.get("mode", "adaptive"),
            rules=voice.get("rules", {}),
            stats=voice.get("stats", {}),
            enforce=enforce,
        )
        from .intent import save_voice_config
        save_voice_config(root, dv)
        print(f"{rule}: upgraded to {enforce[rule]}")
        return

    # Default: show voice config
    print(f"Mode: {voice.get('mode', 'adaptive')}")
    print()
    rules = voice.get("rules", {})
    if rules:
        for key, val in rules.items():
            val_short = val.strip().splitlines()[0] if val else ""
            print(f"  {key}: {val_short}")
    print()
    enforce = voice.get("enforce", {})
    if enforce:
        print("Enforcement:")
        for key, val in enforce.items():
            label = str(val) if val is not False else "off"
            print(f"  {key}: {label}")
    stats = voice.get("stats", {})
    if stats:
        print()
        print("Stats:")
        for key, val in stats.items():
            if val is not None:
                print(f"  {key}: {val}")


def _cmd_conventions(args):
    import json as json_mod
    from .discovery import find_repo_root
    root = find_repo_root(os.getcwd()) or os.getcwd()

    if args.discover:
        from .passes.graph_builder import build_graph
        from .passes.convention_discovery import discover_conventions
        from .passes.convention_parser import parse_conventions
        from .passes.convention_compliance import compute_compliance

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
            from .intent import save_conventions
            save_conventions(root, viable)
            print(f"Accepted {len(viable)} conventions. Written to intent.yaml.")
        else:
            print("Run with --accept to persist, or edit manually in intent.yaml.")
        return

    # List existing conventions
    from .intent import load_conventions
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
    from .discovery import find_repo_root
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

    from .intent import load_conventions
    from .passes.semantic_diff import semantic_diff, format_semantic_diff

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


def _version():
    from . import __version__
    return __version__


if __name__ == "__main__":
    main()
