import argparse
import os
import sys

def _cmd_observe(args):
    from pathlib import Path
    from ..storage.session_manager import SessionManager
    from ..paths.repo import find_repo_root
    from ..ux.visibility import format_observation_delta

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
            from ..storage.onboarding import mark_milestone, increment_counter
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
            from ..engine.utility import compute_utility_scores, save_utility_scores
            all_sessions = mgr.get_sessions(limit=500)
            all_obs = mgr.get_observations(limit=500)
            scores = compute_utility_scores(all_sessions, all_obs)
            save_utility_scores(Path(root) / ".dotscope", scores)
        except Exception:
            pass  # Utility update is best-effort

        # Near-miss detection using structured warning pairs
        try:
            import subprocess
            from ..storage.near_miss import (
                detect_near_misses as detect_nms,
                store_near_misses, load_session_scopes,
            )
            from ..engine.discovery import find_scope
            from ..engine.parser import parse_scope_file

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
            from ..engine.discovery import load_index
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
    from ..paths.repo import find_repo_root
    from ..passes.incremental import incremental_update

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
            pass

def _cmd_hook(args):
    from ..storage.git_hooks import install_hook, uninstall_hook, hook_status
    from ..paths.repo import find_repo_root

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
        from ..storage.claude_hooks import install_claude_hook
        result = install_claude_hook(root)
        print(result)
    else:
        print("Usage: dotscope hook {install|uninstall|status|claude}")

def _cmd_refresh(args):
    from ..paths.repo import find_repo_root
    from ..workflows.refresh import (
        enqueue_commit_refresh,
        enqueue_repo_refresh,
        enqueue_scope_refresh,
        kick_refresh_worker,
        refresh_status_summary,
        run_refresh_inline,
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

    # Default: synchronous refresh (no sub-action)
    scopes = getattr(args, "scopes", []) or []
    is_repo = getattr(args, "repo", False)
    run_async = getattr(args, "run_async", False)

    if run_async:
        if is_repo or not scopes:
            enqueue_repo_refresh(root, reason="cli-async")
        else:
            enqueue_scope_refresh(root, scopes, reason="cli-async")
        kick_refresh_worker(root)
        targets_label = ", ".join(scopes) if scopes else "repo"
        print(f"Queued refresh for {targets_label} (async).")
        return

    result = run_refresh_inline(
        root,
        targets=scopes if scopes else None,
        repo=is_repo,
    )

    targets_label = ", ".join(result.get("targets_refreshed", [])) or "repo"
    if result.get("success"):
        print(f"Refreshed {targets_label} in {result['duration_ms']}ms.")
    else:
        error = result.get("error", "unknown error")
        print(f"Refresh failed for {targets_label}: {error}")

def _cmd_check(args):
    import json as json_mod
    from ..paths.repo import find_repo_root
    from ..passes.sentinel.checker import check_diff, check_staged, format_terminal

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

    explain = getattr(args, "explain", False)

    if args.json_output:
        def _result_dict(r):
            d = {
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
            if explain:
                from ..ux.explain import explain_warning
                d["explain"] = explain_warning(root, r)
            return d

        data = {
            "passed": report.passed,
            "holds": [_result_dict(r) for r in report.holds],
            "notes": [
                {
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "message": r.message,
                    "file": r.file,
                    **({"explain": explain_warning(root, r)} if explain else {}),
                }
                for r in report.notes
            ] if explain else [
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
        if explain:
            from ..ux.explain import explain_warning
        print(json_mod.dumps(data, indent=2))
    else:
        output = format_terminal(report)
        try:
            print(output)
        except UnicodeEncodeError:
            print(output.encode("ascii", errors="replace").decode("ascii"))

        if explain:
            from ..ux.explain import explain_warning, format_explanation
            all_results = list(report.holds) + list(report.notes)
            if all_results:
                print("\n--- Explanations ---")
                for r in all_results:
                    print(f"\n[{r.severity.value.upper()}] {r.message}")
                    exp = explain_warning(root, r)
                    print(format_explanation(exp))

    if not report.passed:
        sys.exit(1)

def _cmd_check_backtest(root, n_commits, json_output):
    """Replay recent commits against checks to validate enforcement."""
    import json as json_mod
    import subprocess
    from ..passes.sentinel.checker import check_diff

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
        from ..storage.onboarding import mark_milestone, next_step
        state = mark_milestone(root, "first_backtest")
        ns = next_step(state)
        if ns:
            print(f"\n{ns}")
    except Exception:
        pass

def _cmd_voice(args):
    import json as json_mod
    from ..paths.repo import find_repo_root
    from ..workflows.intent import load_voice_config

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
        from ..models.intent import DiscoveredVoice
        dv = DiscoveredVoice(
            mode=voice.get("mode", "adaptive"),
            rules=voice.get("rules", {}),
            stats=voice.get("stats", {}),
            enforce=enforce,
        )
        from ..workflows.intent import save_voice_config
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