"""CLI handler for the ``dotscope pro`` subcommand group.

Subcommands:
  - ``status``    : check Pro connection
  - ``compare``   : compare local topology against the Genesis swarm
  - ``density``   : query failure density for a file
  - ``baseline``  : show the global NPMI baseline
  - ``login``     : interactive (or flag-driven) credential setup
  - ``logout``    : remove stored credentials

When Pro is not configured, status/compare/density/baseline print connection
guidance and exit cleanly (return code 0).
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


_DEFAULT_PRO_URL = "https://pro.dotscope.dev"
_MAX_URL_PROMPTS = 3


def _credentials_path() -> Path:
    return Path.home() / ".dotscope" / "credentials"


def _print_connection_help() -> None:
    print("Dotscope Pro: not connected")
    print("")
    print("To connect:")
    print("  1. Set DOTSCOPE_PRO_URL and DOTSCOPE_PRO_TOKEN env vars, or")
    print("  2. Run: dotscope pro login")


def _valid_url(candidate: str) -> bool:
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _prompt_url(default: str = _DEFAULT_PRO_URL) -> str:
    """Prompt for a Pro URL with up to ``_MAX_URL_PROMPTS`` retries."""
    for _ in range(_MAX_URL_PROMPTS):
        raw = input(f"Pro URL [{default}]: ").strip()
        url = raw or default
        if _valid_url(url):
            return url
        print("Invalid URL — must be http(s)://host[:port]", file=sys.stderr)
    raise ValueError("Could not obtain a valid Pro URL after 3 attempts")


def _prompt_yes(question: str, default_no: bool = True) -> bool:
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    answer = input(question + suffix).strip().lower()
    if not answer:
        return not default_no
    return answer in ("y", "yes")


def _write_credentials(url: str, token: str) -> Path:
    """Write the credentials file with restrictive permissions."""
    cred_dir = _credentials_path().parent
    cred_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(cred_dir, 0o700)
        except OSError:
            pass

    path = _credentials_path()
    payload = json.dumps({"pro_url": url, "token": token})
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def _cmd_pro(args) -> None:
    action = getattr(args, "pro_action", None)

    if action == "login":
        _do_login(args)
        return
    if action == "logout":
        _do_logout()
        return

    # All other actions need a live provider.
    from ..pro import get_provider

    pro = get_provider()
    if pro is None:
        _print_connection_help()
        return

    if action == "status":
        healthy = pro.is_healthy()
        print(f"Dotscope Pro: {'connected' if healthy else 'unreachable'}")
        return

    if action == "compare":
        _do_compare(pro)
        return

    if action == "density":
        _do_density(pro, args)
        return

    if action == "baseline":
        _do_baseline(pro)
        return

    # No subaction (`dotscope pro` alone): show status + help hint.
    healthy = pro.is_healthy()
    print(f"Dotscope Pro: {'connected' if healthy else 'unreachable'}")
    print("Run 'dotscope pro --help' for available actions.")


def _do_login(args) -> None:
    flag_url = getattr(args, "url", None)
    flag_token = getattr(args, "token", None)

    if flag_url and flag_token:
        url = flag_url
        token = flag_token
        if not _valid_url(url):
            print("Error: --url must be http(s)://host[:port]", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            url = flag_url if flag_url and _valid_url(flag_url) else _prompt_url()
        except (ValueError, EOFError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        token = flag_token or getpass.getpass("Pro token: ").strip()
        if not token:
            print("Error: token cannot be empty", file=sys.stderr)
            sys.exit(1)

    # Validate against the live backend.
    from ..pro.remote import RemoteProProvider

    provider = RemoteProProvider(url, token)
    if provider.is_healthy():
        path = _write_credentials(url, token)
        print(f"Saved to {path}")
        print(
            "Note: token is stored as plaintext locally (mode 0600 on POSIX). "
            "Same posture as ~/.netrc and ~/.docker/config.json."
        )
        return

    # Backend unreachable — ask whether to save anyway.
    print("Warning: could not reach Pro backend at this URL.", file=sys.stderr)
    if flag_url and flag_token:
        # Non-interactive mode: don't surprise CI by writing on failure.
        print(
            "Refusing to save unverified credentials in non-interactive mode. "
            "Drop --url/--token to confirm interactively.",
            file=sys.stderr,
        )
        sys.exit(1)
    if _prompt_yes("Save credentials anyway?", default_no=True):
        path = _write_credentials(url, token)
        print(f"Saved to {path} (unverified)")
    else:
        print("Aborted — no credentials written.")


def _do_logout() -> None:
    path = _credentials_path()
    if path.exists():
        try:
            path.unlink()
            print(f"Removed {path}")
        except OSError as e:
            print(f"Error removing credentials: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Already logged out.")


def _do_compare(pro) -> None:
    from ..passes.graph_builder import build_graph
    from ..paths.repo import find_repo_root
    from ..pro._anonymize import anonymize_graph

    root = find_repo_root() or os.getcwd()
    graph = build_graph(root)
    anon = anonymize_graph(graph)
    report = pro.compare_topology(anon)

    print(f"Structural analogs: {report.analog_count}")
    for analog in report.analogs[:5]:
        print(
            f"  {analog.repo_domain} - {analog.similarity_score:.0%} similar: "
            f"{analog.insight}"
        )
    if report.anomalies:
        print(f"\nAnomalies ({len(report.anomalies)}):")
        for anomaly in report.anomalies:
            print(f"  ! {anomaly}")
    if report.directives:
        print(f"\nDirectives ({len(report.directives)}):")
        for d in report.directives[:5]:
            print(f"  [{d.severity}] {d.directive_type}: {d.target} - {d.reasoning}")


def _do_density(pro, args) -> None:
    from ..passes.graph_builder import build_graph
    from ..paths.repo import find_repo_root

    root = find_repo_root() or os.getcwd()
    target = os.path.relpath(os.path.abspath(args.file), root)
    graph = build_graph(root)
    node = graph.files.get(target)
    in_degree = len(node.imported_by) if node else 0
    loc = int(getattr(node, "loc", 0) or 0) if node else 0

    fd = pro.get_failure_density(loc_count=loc, in_degree=in_degree)
    print(f"File: {target}")
    print(f"  in_degree: {in_degree}")
    print(f"  loc:       {loc}")
    print(f"  density:   {fd.density * 100:.1f}%")
    print(f"  severity:  {fd.severity}")
    print(f"  matched:   {fd.matched_repos} repos")
    if fd.explanation:
        print(f"  note:      {fd.explanation}")


def _do_baseline(pro) -> None:
    baseline = pro.get_global_npmi_baseline()
    print(f"Genesis Swarm NPMI Baseline ({baseline.repo_count} repos):")
    print(f"  Mean max NPMI: {baseline.mean_max_npmi:.3f}")
    print(f"  P50  max NPMI: {baseline.p50_max_npmi:.3f}")
    print(f"  P90  max NPMI: {baseline.p90_max_npmi:.3f}")
