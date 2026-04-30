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
        # The async run path needs claude-agent-sdk and is intended to be invoked
        # by an operator from a long-running terminal session. Surface a clear
        # message rather than attempt a partial implementation here.
        raise ValueError(
            "dotscope orchestrator run is not yet wired in this build. "
            "Use the orchestrator module's run_pair() programmatically once "
            "claude-agent-sdk is installed (pip install dotscope[trial-orchestrator])."
        )

    raise ValueError(f"unknown orchestrator action: {action}")
