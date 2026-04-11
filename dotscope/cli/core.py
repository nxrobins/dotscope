import argparse
import os
import sys

def _cmd_resolve(args):
    from ..engine.composer import compose
    from ..passes.budget_allocator import apply_budget
    from ..paths.repo import find_repo_root
    from ..ux.formatter import format_resolved
    from ..workflows.refresh import ensure_resolution_freshness

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
    from ..paths.repo import find_repo_root
    from ..engine.discovery import find_resolution_scope
    from ..engine.context import query_context
    from ..workflows.refresh import ensure_resolution_freshness

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
    from ..engine.matcher import match_task
    from ..paths.repo import find_repo_root
    from ..engine.discovery import load_resolution_index, load_resolution_scopes

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
    from ..workflows.ingest import ingest
    result = ingest(root, quiet=quiet)

    # 2. Install hooks
    try:
        from ..storage.git_hooks import install_hook
        install_hook(root)
        if not quiet:
            print("dotscope: hooks installed", file=sys.stderr)
    except Exception as e:
        print(f"dotscope: hook install failed: {e}", file=sys.stderr)

    # 3. Auto-configure MCP for detected IDEs
    try:
        from ..storage.mcp_config import configure_mcp
        configured = configure_mcp(root)
        if configured and not quiet:
            print(f"dotscope: MCP configured for {', '.join(configured)}", file=sys.stderr)
    except Exception as e:
        print(f"dotscope: MCP config failed: {e}", file=sys.stderr)

    # 4. Write AGENT_INSTRUCTIONS.md + CLAUDE.md
    try:
        _write_agent_instructions(root, quiet)
    except Exception as e:
        if not quiet:
            print(f"dotscope: agent instructions failed: {e}", file=sys.stderr)
    try:
        from ..storage.claude_hooks import write_claude_md
        write_claude_md(root)
    except Exception as e:
        if not quiet:
            print(f"dotscope: CLAUDE.md failed: {e}", file=sys.stderr)

    # 5. Backtest as counterfactual demo
    if not quiet:
        try:
            from ..passes.backtest import backtest_scopes
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

def _cmd_utility(args):
    from ..paths.repo import find_repo_root
    from ..storage.session_manager import SessionManager
    from ..engine.utility import compute_utility_scores

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

def _cmd_intent(args):
    from ..paths.repo import find_repo_root
    from ..workflows.intent import load_intents, add_intent, remove_intent

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

def _cmd_sync(args):
    from ..paths.repo import find_repo_root
    from ..workflows.sync import sync_scopes

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    count = sync_scopes(root, getattr(args, "scopes", None))
    if count == 0:
        print("No scopes were modified.")
    else:
        print(f"\nSuccessfully synchronized {count} scope(s).")