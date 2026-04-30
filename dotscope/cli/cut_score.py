"""CLI subcommand for `dotscope cut-score`."""

from __future__ import annotations

import json
import os
import sys


def _cmd_cut_score(args):
    from ..cut_score import (
        CutScoreError,
        parse_label_overrides,
        parse_module_style_overrides,
        run_cut_score,
        write_report,
    )

    if not args.repo:
        raise ValueError("at least one --repo is required")

    label_overrides = parse_label_overrides(args.label_override or [])
    module_style_overrides = parse_module_style_overrides(args.module_style_override or [])
    token = os.environ.get(args.token_env) if args.token_env else None

    try:
        payload = run_cut_score(
            repos=list(args.repo),
            n=args.n,
            token=token,
            label_overrides=label_overrides,
            default_module_style=args.module_style,
            module_style_overrides=module_style_overrides,
        )
    except CutScoreError as exc:
        raise ValueError(str(exc))

    if args.out:
        write_report(payload, args.out)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_summary(payload)

    if payload["any_repo_failed_gate"]:
        sys.exit(1)


def _print_summary(payload):
    print(f"cut-score v{payload['cut_score_version']}")
    print(f"n_per_repo: {payload['n_per_repo']}")
    print(f"default_module_style: {payload['default_module_style']}")
    print()
    for entry in payload["repos"]:
        s = entry["summary"]
        gate = "PASS" if s["gate_passed"] else "FAIL"
        print(
            f"{s['repo']}: {gate} "
            f"public={s['qualifying_rate_public']:.0%} "
            f"diagnostic={s['qualifying_rate_diagnostic']:.0%} "
            f"(n={s['n_examined']}, "
            f"module_style={entry['module_style_used']} via {entry['module_style_source']})"
        )
        if s.get("module_style_warning"):
            print(f"    warning: {s['module_style_warning']}")
        if s.get("fallback_recommendation"):
            print(f"    fallback: {s['fallback_recommendation']}")
