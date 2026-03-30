"""Core check pipeline: run all checks against a diff."""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from .models import CheckReport, CheckResult, Severity
from ...textio import read_repo_text
from .checks.boundary import check_boundaries
from .checks.contracts import check_contracts
from .checks.antipattern import check_antipatterns
from .checks.direction import check_dependency_direction
from .checks.stability import check_stability
from .checks.convention import check_conventions
from .checks.intent import check_intent_holds, check_intent_notes
from .checks.voice import check_voice
from .checks.spatial import check_colocation
from .acknowledge import is_acknowledged


def check_diff(
    diff_text: str,
    repo_root: str,
    session_id: Optional[str] = None,
    acknowledge_ids: Optional[List[str]] = None,
) -> CheckReport:
    """Run all checks against a diff.

    Args:
        diff_text: Unified diff text
        repo_root: Repository root path
        session_id: Optional session ID for boundary checking
        acknowledge_ids: IDs to treat as pre-acknowledged
    """
    modified_files, added_lines = _parse_diff(diff_text)

    if not modified_files:
        return CheckReport(passed=True, files_checked=0, checks_run=0)

    # Cap enormous diffs (with warning)
    capped = False
    total_files = len(modified_files)
    if total_files > 100:
        modified_files = modified_files[:100]
        capped = True

    # Load all data
    invariants = _load_invariants(repo_root)
    scopes = _load_scopes_with_antipatterns(repo_root)
    graph_hubs = _load_graph_hubs(repo_root)
    session = _resolve_session(repo_root, session_id)
    intents = _load_intents(repo_root)
    conventions, convention_ast = _load_conventions_and_ast(repo_root, modified_files)
    voice_config = _load_voice_config(repo_root)

    results: List[CheckResult] = []

    # HOLDs
    results.extend(check_boundaries(modified_files, session, scopes))
    results.extend(check_contracts(modified_files, invariants, diff_text))
    results.extend(check_antipatterns(added_lines, scopes, repo_root))
    results.extend(check_intent_holds(modified_files, added_lines, intents))
    results.extend(check_conventions(modified_files, added_lines, conventions, convention_ast))
    results.extend(check_voice(modified_files, added_lines, voice_config, repo_root))

    # NOTEs
    results.extend(check_dependency_direction(added_lines, graph_hubs, scopes))
    results.extend(check_stability(modified_files, diff_text, invariants))
    results.extend(check_intent_notes(modified_files, added_lines, intents))
    results.extend(check_colocation(modified_files, graph_hubs, repo_root))

    # Warn if files were capped
    if capped:
        results.append(CheckResult(
            passed=False,
            category=CheckCategory.STABILITY,
            severity=Severity.NOTE,
            message=f"Large diff: checked 100 of {total_files} files",
            detail=f"Files beyond position 100 were not checked.",
            file=None,
        ))

    # Gap 3: NUDGE escalation — repeated nudges become guards
    from .acknowledge import (
        record_nudge_occurrence, record_nudge_resolution, is_escalated,
    )
    # Track which nudge IDs fired this run
    fired_nudge_ids = set()
    for r in results:
        if r.severity == Severity.NUDGE and not r.passed and r.acknowledge_id:
            fired_nudge_ids.add(r.acknowledge_id)
            record_nudge_occurrence(repo_root, r.acknowledge_id)
            if is_escalated(repo_root, r.acknowledge_id):
                r.severity = Severity.GUARD

    # Record resolutions: nudges that were previously tracked but didn't fire
    # this run have been fixed — reset their escalation counter
    try:
        nudge_path = os.path.join(repo_root, ".dotscope", "nudge_occurrences.jsonl")
        if os.path.exists(nudge_path):
            known_ids: set = set()
            with open(nudge_path, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line:
                        try:
                            _entry = json.loads(_line)
                            if not _entry.get("resolved"):
                                known_ids.add(_entry.get("id", ""))
                        except json.JSONDecodeError:
                            pass
            for kid in known_ids:
                if kid and kid not in fired_nudge_ids:
                    record_nudge_resolution(repo_root, kid)
    except Exception:
        pass

    # Filter acknowledged
    ack_set = set(acknowledge_ids or [])
    for r in results:
        if r.acknowledge_id and (
            r.acknowledge_id in ack_set
            or is_acknowledged(repo_root, r.acknowledge_id)
        ):
            r.passed = True

    # Only GUARDs block commits. NUDGEs and NOTEs pass through.
    passed = not any(
        r.severity.blocks_commit and not r.passed
        for r in results
    )

    return CheckReport(
        passed=passed,
        results=[r for r in results if not r.passed],
        files_checked=len(modified_files),
        checks_run=9,
    )


def check_staged(repo_root: str, session_id: Optional[str] = None) -> CheckReport:
    """Check currently staged changes."""
    diff_text = _get_staged_diff(repo_root)
    if not diff_text:
        return CheckReport(passed=True, files_checked=0, checks_run=0)
    return check_diff(diff_text, repo_root, session_id=session_id)


def format_terminal(report: CheckReport) -> str:
    """Format a check report for terminal output."""
    if report.passed and not report.nudges and not report.notes:
        return f"dotscope: {report.files_checked} files, {report.checks_run} checks -- clear"

    lines = [f"dotscope: checking {report.files_checked} files"]
    lines.append("")

    for r in report.guards:
        lines.append(f"  GUARD  {r.category.value}")
        lines.append(f"    {r.message}")
        if r.suggestion:
            lines.append(f"    -> {r.suggestion}")
        if r.can_acknowledge and r.acknowledge_id:
            lines.append(f"    -> Acknowledge: dotscope check --acknowledge {r.acknowledge_id}")
        lines.append("")

    for r in report.nudges:
        lines.append(f"  NUDGE  {r.category.value}")
        lines.append(f"    {r.message}")
        if r.suggestion:
            lines.append(f"    -> {r.suggestion}")
        if r.proposed_fix and r.proposed_fix.predicted_sections:
            sections = ", ".join(r.proposed_fix.predicted_sections)
            lines.append(f"    Likely needs changes: {sections}")
        lines.append("")

    for r in report.notes:
        lines.append(f"  NOTE  {r.category.value}")
        lines.append(f"    {r.message}")
        lines.append("")

    guard_count = len(report.guards)
    nudge_count = len(report.nudges)
    note_count = len(report.notes)
    if guard_count:
        lines.append(f"dotscope: {guard_count} guard(s), {nudge_count} nudge(s), {note_count} note(s) -- address guards to proceed")
    elif nudge_count:
        lines.append(f"dotscope: {nudge_count} nudge(s), {note_count} note(s) -- clear (nudges are guidance, not gates)")
    else:
        lines.append(f"dotscope: {note_count} note(s) -- clear")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _parse_diff(diff_text: str) -> tuple:
    """Parse unified diff into modified files and added lines per file."""
    modified_files: List[str] = []
    added_lines: Dict[str, List[str]] = {}
    current_file = ""

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            if len(parts) > 1:
                current_file = parts[1]
                if current_file not in modified_files:
                    modified_files.append(current_file)
                added_lines.setdefault(current_file, [])
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            added_lines.setdefault(current_file, []).append(line[1:])

    return modified_files, added_lines


def _get_staged_diff(repo_root: str) -> str:
    """Get git diff of staged changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _load_invariants(repo_root: str) -> dict:
    """Load invariants.json from .dotscope/, pruning stale references."""
    path = os.path.join(repo_root, ".dotscope", "invariants.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

    # Prune contracts referencing files that no longer exist
    contracts = data.get("contracts", [])
    if contracts:
        valid = []
        for c in contracts:
            trigger = c.get("trigger_file", "")
            coupled = c.get("coupled_file", "")
            if (os.path.isfile(os.path.join(repo_root, trigger))
                    and os.path.isfile(os.path.join(repo_root, coupled))):
                valid.append(c)
        data["contracts"] = valid

    return data


def _load_scopes_with_antipatterns(repo_root: str) -> Dict[str, dict]:
    """Load scope files with anti_patterns field."""
    from ...discovery import find_all_scopes
    from ...parser import parse_scope_file, _parse_yaml

    scopes = {}
    for sf in find_all_scopes(repo_root):
        try:
            rel_dir = os.path.relpath(os.path.dirname(sf), repo_root)
            if rel_dir == ".":
                rel_dir = ""

            # Parse the raw YAML to get anti_patterns (not in ScopeConfig model)
            raw = _parse_yaml(read_repo_text(sf).text)

            scopes[rel_dir] = {
                "anti_patterns": raw.get("anti_patterns", []),
            }
        except (ValueError, IOError):
            continue

    return scopes


def _load_graph_hubs(repo_root: str) -> Dict[str, object]:
    """Load cached graph hubs."""
    try:
        from ...cache import load_cached_graph_hubs
        return load_cached_graph_hubs(repo_root)
    except Exception:
        return {}


def _resolve_session(
    repo_root: str,
    session_id: Optional[str] = None,
) -> Optional[dict]:
    """Resolve which session to check boundaries against.

    1. Explicit session_id → load that session
    2. No session_id → find most recent session within 10 minutes
    3. Fallback → None (skip boundary check)
    """
    sessions_dir = os.path.join(repo_root, ".dotscope", "sessions")

    if session_id:
        path = os.path.join(sessions_dir, f"{session_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    if os.path.isdir(sessions_dir):
        sessions = sorted(
            Path(sessions_dir).glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in sessions[:5]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    session = json.load(f)
                ts = session.get("timestamp", 0)
                if time.time() - ts < 600:  # 10 minutes
                    return session
            except (json.JSONDecodeError, IOError):
                continue

    return None


def _load_intents(repo_root: str) -> list:
    """Load architectural intents."""
    try:
        from ...intent import load_intents
        return load_intents(repo_root)
    except Exception:
        return []


def _load_conventions_and_ast(
    repo_root: str,
    modified_files: List[str],
) -> tuple:
    """Load conventions and parse AST for modified files."""
    try:
        from ...intent import load_conventions
        conventions = load_conventions(repo_root)
    except Exception:
        conventions = []

    ast_data = {}
    if conventions:
        try:
            from ..ast_analyzer import analyze_file
            for filepath in modified_files:
                full_path = os.path.join(repo_root, filepath)
                if os.path.isfile(full_path):
                    lang = _detect_language(filepath)
                    if lang:
                        analysis = analyze_file(full_path, lang)
                        if analysis:
                            ast_data[filepath] = analysis
        except Exception:
            pass

    return conventions, ast_data


def _detect_language(filepath: str) -> Optional[str]:
    """Detect language from file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",
    }.get(ext)


def _load_voice_config(repo_root: str) -> Optional[dict]:
    """Load voice config from intent.yaml."""
    try:
        from ...intent import load_voice_config
        return load_voice_config(repo_root)
    except Exception:
        return None
