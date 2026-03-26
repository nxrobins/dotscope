"""Architectural intent checks: validate changes against declared direction."""

import re
from typing import Dict, List

from ..models import CheckCategory, CheckResult, ProposedFix, Severity, IntentDirective


def check_intent_holds(
    modified_files: List[str],
    added_lines: Dict[str, List[str]],
    intents: List[IntentDirective],
) -> List[CheckResult]:
    """Check for HOLD-level intent violations (deprecate, freeze)."""
    results = []

    for intent in intents:
        if intent.directive == "deprecate":
            results.extend(_check_deprecate(added_lines, intent))
        elif intent.directive == "freeze":
            results.extend(_check_freeze(modified_files, intent))

    return results


def check_intent_notes(
    modified_files: List[str],
    added_lines: Dict[str, List[str]],
    intents: List[IntentDirective],
) -> List[CheckResult]:
    """Check for NOTE-level intent violations (decouple, consolidate)."""
    results = []

    for intent in intents:
        if intent.directive == "decouple":
            results.extend(_check_decouple(added_lines, intent))
        elif intent.directive == "consolidate":
            results.extend(_check_consolidate(modified_files, intent))

    return results


def _check_deprecate(
    added_lines: Dict[str, List[str]],
    intent: IntentDirective,
) -> List[CheckResult]:
    """New usage of deprecated files is a HOLD."""
    results = []
    deprecated = set(intent.files)

    import_re = re.compile(
        r'(?:from\s+(\S+)\s+import|import\s+(\S+))'
    )

    from ..line_filter import strip_comments_and_strings

    for filepath, lines in added_lines.items():
        # Don't flag the deprecated file itself
        if filepath in deprecated:
            continue

        for line_text in lines:
            code_only = strip_comments_and_strings(line_text)
            if not code_only.strip():
                continue
            m = import_re.search(code_only)
            if not m:
                continue
            imported = (m.group(1) or m.group(2) or "").replace(".", "/")
            for dep_file in deprecated:
                dep_module = dep_file.replace(".py", "").replace("/", ".")
                dep_path = dep_file.replace(".py", "")
                if dep_module in (m.group(1) or "") or dep_path in imported:
                    fix = None
                    if intent.replacement:
                        fix = ProposedFix(
                            file=intent.replacement,
                            reason=f"Use {intent.replacement} instead of {dep_file}",
                            confidence=1.0,
                        )
                    results.append(CheckResult(
                        passed=False,
                        category=CheckCategory.INTENT,
                        severity=Severity.GUARD,
                        message=f"{dep_file} is deprecated: {intent.reason}",
                        detail=f"New import in {filepath}",
                        file=filepath,
                        suggestion=f"Use {intent.replacement}" if intent.replacement else "Remove usage",
                        proposed_fix=fix,
                        can_acknowledge=True,
                        acknowledge_id=f"intent_deprecate_{intent.id}",
                    ))
                    break

    return results


def _check_freeze(
    modified_files: List[str],
    intent: IntentDirective,
) -> List[CheckResult]:
    """Any change to frozen modules is a GUARD."""
    results = []
    frozen = set(intent.modules)

    for filepath in modified_files:
        for module in frozen:
            if filepath.startswith(module):
                results.append(CheckResult(
                    passed=False,
                    category=CheckCategory.INTENT,
                    severity=Severity.GUARD,
                    message=f"{module} is frozen: {intent.reason}",
                    detail=f"Modified {filepath}",
                    file=filepath,
                    suggestion="Requires explicit acknowledgment to proceed",
                    can_acknowledge=True,
                    acknowledge_id=f"intent_freeze_{intent.id}",
                ))
                break

    return results


def _check_decouple(
    added_lines: Dict[str, List[str]],
    intent: IntentDirective,
) -> List[CheckResult]:
    """New coupling between decoupling-targeted modules is a NOTE."""
    results = []
    if len(intent.modules) < 2:
        return results

    modules = intent.modules
    import_re = re.compile(
        r'(?:from\s+(\S+)\s+import|import\s+(\S+))'
    )

    from ..line_filter import strip_comments_and_strings

    for filepath, lines in added_lines.items():
        file_module = _file_to_module(filepath)
        if file_module not in modules:
            continue

        for line_text in lines:
            code_only = strip_comments_and_strings(line_text)
            if not code_only.strip():
                continue
            m = import_re.search(code_only)
            if not m:
                continue
            imported = (m.group(1) or m.group(2) or "").split(".")[0]
            imported_mod = imported + "/"
            if imported_mod in modules and imported_mod != file_module:
                results.append(CheckResult(
                    passed=False,
                    category=CheckCategory.INTENT,
                    severity=Severity.NOTE,
                    message=(
                        f"New coupling: {file_module} -> {imported_mod} "
                        f"(intent: decouple, set {intent.set_at})"
                    ),
                    detail=intent.reason,
                    file=filepath,
                ))
                break  # One per file

    return results


def _check_consolidate(
    modified_files: List[str],
    intent: IntentDirective,
) -> List[CheckResult]:
    """Code moving away from consolidation target is a NOTE."""
    results = []
    if not intent.target or len(intent.modules) < 1:
        return results

    target = intent.target
    source_modules = [m for m in intent.modules if m != target]

    for filepath in modified_files:
        for mod in source_modules:
            if filepath.startswith(mod):
                # A change to a source module (not moving toward target) is a note
                results.append(CheckResult(
                    passed=False,
                    category=CheckCategory.INTENT,
                    severity=Severity.NOTE,
                    message=(
                        f"Changes to {mod}, intent is to consolidate into {target} "
                        f"(set {intent.set_at})"
                    ),
                    detail=intent.reason,
                    file=filepath,
                ))
                break

    return results


def _file_to_module(filepath: str) -> str:
    """Extract the top-level module directory from a file path."""
    parts = filepath.split("/")
    return parts[0] + "/" if len(parts) > 1 else ""
