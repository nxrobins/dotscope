import json
import sys


def _cmd_trial(args):
    from ..paths.repo import find_repo_root
    from ..trial import PublicReportError, TrialStore, format_trial_report

    root = find_repo_root()
    if root is None:
        raise ValueError("Could not find repository root")

    store = TrialStore(root)

    if args.trial_action == "pair":
        if args.trial_pair_action != "new":
            raise ValueError("Usage: dotscope trial pair new ...")
        pair = store.create_pair(
            task=args.task,
            model=args.model,
            client=args.client,
            project=args.project,
            base_ref=args.base_ref,
            pair_id=args.pair_id,
            order_policy=args.order_policy,
        )
        print(json.dumps(pair, indent=2) if args.json else pair["pair_id"])
        return

    if args.trial_action == "start":
        trial = store.start_trial(
            pair_id=args.pair_id,
            arm=args.arm,
            worktree=args.worktree,
            token_boundary=args.token_boundary,
            token_fidelity=args.token_fidelity,
            capture_method=args.capture_method or "",
            tokenizer_encoding=args.tokenizer_encoding or "",
            timeout_hours=args.timeout_hours,
        )
        if args.json:
            print(json.dumps(trial, indent=2))
            return
        clean = "clean" if trial["clean_start"] else "dirty"
        print(f"{trial['trial_id']} ({trial['arm']}, {clean})")
        if not trial["clean_start"]:
            print(
                "dirty starts are diagnostic only and excluded from public reports",
                file=sys.stderr,
            )
        return

    if args.trial_action == "finish":
        trial = store.finish_trial(
            trial_id=args.trial_id,
            commits=args.commits,
            validations=args.validation,
            validation_runs=args.validation_runs,
        )
        print(
            json.dumps(trial, indent=2)
            if args.json
            else f"{trial['trial_id']} {trial['validation_status']}"
        )
        return

    if args.trial_action == "cancel":
        trial = store.cancel_trial(args.trial_id)
        print(json.dumps(trial, indent=2) if args.json else f"{trial['trial_id']} cancelled")
        return

    if args.trial_action == "status":
        status = store.status()
        if args.json:
            print(json.dumps(status, indent=2))
            return
        active = status.get("active")
        if active:
            print(f"active: {active['trial_id']} ({active['arm']})")
        else:
            print("active: none")
        print(f"pairs: {status['pair_count']}")
        print(f"trials: {status['trial_count']}")
        return

    if args.trial_action == "compare":
        comparison = store.compare_pair(args.pair_id)
        print(json.dumps(comparison, indent=2) if args.json else _format_compare(comparison))
        return

    if args.trial_action == "report":
        try:
            report = store.report(public=args.public)
        except PublicReportError as exc:
            report = exc.report
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(format_trial_report(report))
            failed = [gate for gate in report.get("gates", []) if not gate.get("passed")]
            for gate in failed:
                print(f"public gate failed: {gate['name']}", file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(report, indent=2) if args.json else format_trial_report(report))
        return

    if args.trial_action == "record":
        if args.trial_record_action != "tokens":
            raise ValueError("Usage: dotscope trial record tokens ...")
        event = store.record_tokens(
            trial_id=args.trial_id,
            input_tokens=args.input_tokens,
            token_boundary=args.token_boundary,
            token_fidelity=args.token_fidelity,
            capture_method=args.capture_method or "",
            tokenizer_encoding=args.tokenizer_encoding or "",
            source=args.source,
            turn_id=args.turn_id,
        )
        print(json.dumps(event, indent=2) if args.json else f"recorded event {event['event_id']}")
        return

    raise ValueError(
        "Usage: dotscope trial {pair|start|finish|status|cancel|compare|report|record}"
    )


def _format_compare(comparison):
    lines = [f"pair: {comparison['pair_id']}"]
    lines.append(f"public valid: {comparison['public_valid']}")
    if comparison["reasons"]:
        lines.append("reasons:")
        for reason in comparison["reasons"]:
            lines.append(f"  - {reason}")
    if comparison.get("paired_token_delta_pct") is not None:
        lines.append(f"paired_token_delta_pct: {comparison['paired_token_delta_pct']:.3f}%")
    if comparison.get("paired_success_delta_pp") is not None:
        lines.append(f"paired_success_delta_pp: {comparison['paired_success_delta_pp']:.3f}pp")
    return "\n".join(lines)
