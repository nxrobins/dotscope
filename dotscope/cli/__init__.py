from .core import _cmd_resolve, _cmd_context, _cmd_match, _cmd_init, _cmd_intent, _cmd_utility, _cmd_sync, _cmd_doctor
from .observability import _cmd_stats, _cmd_tree, _cmd_health, _cmd_validate, _cmd_virtual, _cmd_lessons, _cmd_invariants, _cmd_rebuild, _cmd_test_compiler, _cmd_bench, _cmd_debug
from .ingest import _cmd_ingest, _cmd_impact, _cmd_backtest, _cmd_conventions, _cmd_diff, _cmd_bootstrap
from .hooks import _cmd_observe, _cmd_incremental, _cmd_hook, _cmd_refresh, _cmd_check, _cmd_check_backtest, _cmd_voice
from .serve import _cmd_serve


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
    from ..ux.textio import consume_decode_warnings

    consume_decode_warnings()

    # Intercept help before argparse touches it
    args_list = argv if argv is not None else sys.argv[1:]
    if not args_list or args_list == ["help"] or args_list == ["--help"] or args_list == ["-h"]:
        from ..ux.help import print_help
        print_help()
        return
    if len(args_list) >= 2 and args_list[1] in ("--help", "-h"):
        from ..ux.help import print_help, HELP_COMMANDS
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

    # --- sync ---
    p_sync = sub.add_parser("sync", help="Re-align .scope boundaries against the current import graph")
    p_sync.add_argument("scopes", nargs="*", help="Specific scopes to sync (omit for entire repo)")

    # --- ingest ---
    p_ingest = sub.add_parser("ingest", help="Reverse-engineer .scope files from an existing codebase")
    p_ingest.add_argument("directory", nargs="?", default=None, help="Repository root to ingest (default: current directory)")
    p_ingest.add_argument("--dir", default=None, help="Repository root to ingest (alias for positional arg)")
    p_ingest.add_argument("--no-history", action="store_true", help="Skip git history mining")
    p_ingest.add_argument("--no-docs", action="store_true", help="Skip doc absorption")
    p_ingest.add_argument("--dry-run", action="store_true", help="Plan only, don't write files")
    p_ingest.add_argument("--max-commits", type=int, default=500, help="Max git commits to analyze")
    p_ingest.add_argument("--quiet", action="store_true", help="Suppress progress output (for CI)")
    p_ingest.add_argument("--voice", choices=["prescriptive", "adaptive"], default=None,
                          help="Override voice mode (prescriptive for new, adaptive for existing)")

    # --- bootstrap ---
    p_bootstrap = sub.add_parser("bootstrap", help="Output Phase 2 payload for automated tool handoff")
    p_bootstrap.add_argument("--dir", default=".", help="Repository root")

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
    p_refresh = sub.add_parser("refresh", help="Refresh scopes (synchronous by default)")
    p_refresh.add_argument("scopes", nargs="*", help="Scope names to refresh (omit for full repo)")
    p_refresh.add_argument("--repo", action="store_true", help="Force full repo refresh")
    p_refresh.add_argument("--async", dest="run_async", action="store_true", help="Queue and return (legacy async mode)")
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
    p_check.add_argument("--explain", action="store_true", help="Show full provenance for each finding")

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

    # --- doctor ---
    p_doctor = sub.add_parser("doctor", help="Diagnose runtime integrations and startup paths")
    doctor_sub = p_doctor.add_subparsers(dest="doctor_target")
    p_doctor_mcp = doctor_sub.add_parser("mcp", help="Verify MCP launcher selection and client config health")
    p_doctor_mcp.add_argument("path", nargs="?", default=".", help="Repository root")
    p_doctor_mcp.add_argument("--json", action="store_true", help="Output as JSON")

    # --- serve ---
    p_serve = sub.add_parser("serve", help="Launch interactive 3D topography dashboard")
    p_serve.add_argument("--port", type=int, default=8080, help="Port to run the local server on")
    p_serve.add_argument("--headless", action="store_true", help="Launch the API server exclusively without WebGPU payload mounting")

    args = parser.parse_args(argv)

    if args.command is None or getattr(args, "show_help", False):
        from ..ux.help import print_help
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
            "sync": _cmd_sync,
            "ingest": _cmd_ingest,
            "bootstrap": _cmd_bootstrap,
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
            "doctor": _cmd_doctor,
            "serve": _cmd_serve,
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

def _print_counterfactual(ingest_result, backtest, violations):
    import sys

    # STRICT ALIGNMENT: Zero placeholders.
    if isinstance(ingest_result, dict):
        total_repo_tokens = ingest_result.get("total_repo_tokens")
        avg_scope_tokens = ingest_result.get("avg_scope_tokens")
        scopes_written = ingest_result.get("scopes_written", 0)
    else:
        total_repo_tokens = getattr(ingest_result, "total_repo_tokens", None) or None
        scope_list = getattr(ingest_result, "scopes", []) or []
        real_scopes = [s for s in scope_list if not getattr(s, "directory", "").startswith("virtual/")]
        scopes_written = len(real_scopes)
        if total_repo_tokens and real_scopes:
            avg_scope_tokens = sum(
                getattr(getattr(s, "config", s), "tokens_estimate", 0) or 0
                for s in real_scopes
            ) / len(real_scopes) or None
        else:
            avg_scope_tokens = None

    # Use native ANSI for a clean, terminal-safe UI
    GREEN = "\033[92m" if sys.stdout.isatty() else ""
    RESET = "\033[0m" if sys.stdout.isatty() else ""

    print(f"\n  ⠋ Awakening repository...")
    if scopes_written > 0:
        print(f"  {GREEN}✓{RESET} Mapped {scopes_written} structural boundaries.")
    
    # We state the token reduction ONLY if the engine successfully calculated it
    if total_repo_tokens is not None and avg_scope_tokens is not None:
        print(f"  {GREEN}✓{RESET} Context payload optimized: ~{int(avg_scope_tokens):,} tokens (down from ~{total_repo_tokens:,}).")

    print(f"\n  {GREEN}[✓]{RESET} Dotscope is active. Your AI is now structurally aware.\n")

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

    # 2. Write the strict Cursor/Windsurf rules
    manifesto = (
        "CRITICAL REPOSITORY RULES:\n\n"
        "This codebase is structurally managed by Dotscope.\n\n"
        "You are FORBIDDEN from using standard file search. You must use `dotscope_search` to locate code.\n\n"
        "Before modifying any file with an architectural_gravity of HIGH or CRITICAL HUB, you must review its structural_dependencies to ensure you do not break downstream contracts.\n"
    )

    for rule_file in [".cursorrules", ".windsurfrules"]:
        rule_target = os.path.join(root, rule_file)
        if not os.path.exists(rule_target):
            with open(rule_target, "w", encoding="utf-8") as f:
                f.write(manifesto)
            if not quiet:
                print(f"dotscope: {rule_file} generated", file=sys.stderr)
def _print_summary(ingest_result):
    """Fallback when backtest isn't available."""
    print("", file=sys.stderr)
    print("  Your agents are ready.", file=sys.stderr)
    print("", file=sys.stderr)

def _version():
    from .. import __version__
    return __version__

if __name__ == "__main__":
    main()
