"""CLI subcommand for `dotscope orchestrator`."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _cmd_orchestrator(args):
    from ..orchestrator import (
        ConfigFinding,
        OrchestratorError,
        REGRESSION_CACHE_DIR,
        assert_no_inherited_mcp_config,
        verify_regression,
    )

    action = getattr(args, "orchestrator_action", None)
    if action is None:
        raise ValueError(
            "Usage: dotscope orchestrator {contamination-check|verify-regression|run}"
        )

    if action == "contamination-check":
        worktree = Path(args.worktree).resolve() if args.worktree else Path.cwd()
        findings = assert_no_inherited_mcp_config(
            worktree, fail_loud=args.fail_loud,
        )
        report = {
            "worktree": str(worktree),
            "findings": [
                {"path": f.path, "kind": f.kind} for f in findings
            ],
            "fail_loud": args.fail_loud,
            "passed": not findings,
        }
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            if not findings:
                print(f"contamination-check: clean ({worktree})")
            else:
                print(f"contamination-check: {len(findings)} finding(s)")
                for f in findings:
                    print(f"  {f.kind}: {f.path}")
        if findings and args.fail_loud:
            sys.exit(1)
        return

    if action == "verify-regression":
        worktree_root = Path(args.worktree_root).resolve()
        cache_dir = (
            Path(args.cache_dir).expanduser().resolve()
            if args.cache_dir else REGRESSION_CACHE_DIR
        )
        try:
            status = verify_regression(
                repo=args.repo,
                pr=args.pr,
                parent_sha=args.parent_sha,
                test_path=args.test_path,
                worktree_root=worktree_root,
                cut_score_version=args.cut_score_version,
                validation_runs=args.validation_runs,
                cache_dir=cache_dir,
            )
        except OrchestratorError as exc:
            raise ValueError(str(exc))
        payload = {
            "is_regression": status.is_regression,
            "reason": status.reason,
            "cache_hit": status.cache_hit,
            "runs": status.runs,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            cache = "cached" if status.cache_hit else "fresh"
            print(f"verify-regression: {status.reason} ({cache})")
        if not status.is_regression:
            sys.exit(2)  # 2 = task should be skipped, distinct from real failure
        return

    if action == "run":
        return _run_corpus_cli(args)

    raise ValueError(f"unknown orchestrator action: {action}")


def _run_corpus_cli(args):
    """Drive `dotscope orchestrator run` end-to-end.

    Loads the cut-score JSON, resolves the SDK adapter, finds the dotscope
    repo root for trial state, and dispatches into orchestrator.run_corpus.
    Prints per-task progress and a final summary; exits 1 on any error.
    """
    import asyncio
    import dataclasses
    import json
    import sys as _sys
    from pathlib import Path

    from ..orchestrator import (
        CorpusResult,
        OrchestratorError,
        load_real_sdk_adapter,
        run_corpus,
    )
    from ..paths.repo import find_repo_root
    from ..trial import TrialStore

    tasks_path = Path(args.tasks).expanduser().resolve()
    if not tasks_path.exists():
        raise ValueError(f"tasks file not found: {tasks_path}")
    cut_score_payload = json.loads(tasks_path.read_text(encoding="utf-8"))

    worktrees_root = Path(args.worktrees_root).expanduser().resolve()
    worktrees_root.mkdir(parents=True, exist_ok=True)
    audit_dir = (
        Path(args.audit_dir).expanduser().resolve()
        if args.audit_dir else None
    )
    if audit_dir:
        audit_dir.mkdir(parents=True, exist_ok=True)

    repo_root = find_repo_root()
    if repo_root is None:
        raise ValueError("could not find dotscope repository root")
    store = TrialStore(repo_root)

    try:
        adapter = load_real_sdk_adapter()
    except OrchestratorError as exc:
        raise ValueError(str(exc))

    def progress(msg: str) -> None:
        print(msg, file=_sys.stderr, flush=True)

    cut_score_version = cut_score_payload.get("cut_score_version", "1.0")

    result: CorpusResult = asyncio.run(run_corpus(
        store=store,
        cut_score_payload=cut_score_payload,
        pairs_per_repo=args.pairs_per_repo,
        base_ref=args.base_ref,
        model=args.model,
        client=args.client,
        worktrees_root=worktrees_root,
        sdk_query=adapter["sdk_query"],
        is_assistant_message=adapter["is_assistant_message"],
        extract_message_id_and_usage=adapter["extract_message_id_and_usage"],
        extract_text_content=adapter["extract_text_content"],
        validation_runs=args.validation_runs,
        timeout_hours=args.max_arm_hours,
        audit_dir=audit_dir,
        cut_score_version=cut_score_version,
        pre_flight=not args.skip_pre_flight,
        on_progress=progress,
    ))

    payload = {
        "schema_version": 1,
        "completed_pairs": result.completed_pairs,
        "skipped_tasks": result.skipped_tasks,
        "per_repo_summary": result.per_repo_summary,
        "aggregate_attempted": result.aggregate_attempted,
        "aggregate_public_valid": result.aggregate_public_valid,
    }

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        progress(f"wrote: {out_path}")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"corpus run: attempted={result.aggregate_attempted} "
            f"public_valid={result.aggregate_public_valid} "
            f"skipped={len(result.skipped_tasks)}"
        )
        for repo, stats in sorted(result.per_repo_summary.items()):
            print(
                f"  {repo}: attempted={stats['attempted']} "
                f"completed={stats['completed']} "
                f"public_valid={stats['public_valid']} "
                f"skipped={stats['skipped']}"
            )
