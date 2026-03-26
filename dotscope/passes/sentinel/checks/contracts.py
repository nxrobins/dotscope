"""Implicit contract check: coupled files modified without their pair."""

import hashlib
from typing import Dict, List, Optional

from ..models import CheckCategory, CheckResult, ProposedFix, Severity


def check_contracts(
    modified_files: List[str],
    invariants: dict,
    diff_text: str,
) -> List[CheckResult]:
    """Check implicit contracts — if A changed, did B change too?"""
    contracts = invariants.get("contracts", [])
    if not contracts:
        return []

    modified_set = set(modified_files)
    results = []

    for contract in contracts:
        trigger = contract.get("trigger_file", "")
        coupled = contract.get("coupled_file", "")
        confidence = contract.get("confidence", 0.0)

        if confidence < 0.65:
            continue

        # Both modified → satisfied
        if trigger in modified_set and coupled in modified_set:
            continue

        # Only one side modified → violation
        if trigger in modified_set and coupled not in modified_set:
            fix = _build_fix_proposal(trigger, coupled, diff_text, invariants)
            ack_id = _ack_id(trigger, coupled)
            results.append(CheckResult(
                passed=False,
                category=CheckCategory.CONTRACT,
                severity=Severity.NUDGE,
                message=(
                    f"{trigger} modified without {coupled} "
                    f"({confidence:.0%} co-change rate)"
                ),
                detail=contract.get("description", ""),
                file=trigger,
                suggestion=f"Review {coupled} for necessary changes",
                proposed_fix=fix,
                can_acknowledge=True,
                acknowledge_id=ack_id,
            ))

        elif coupled in modified_set and trigger not in modified_set:
            fix = _build_fix_proposal(coupled, trigger, diff_text, invariants)
            ack_id = _ack_id(coupled, trigger)
            results.append(CheckResult(
                passed=False,
                category=CheckCategory.CONTRACT,
                severity=Severity.NUDGE,
                message=(
                    f"{coupled} modified without {trigger} "
                    f"({confidence:.0%} co-change rate)"
                ),
                detail=contract.get("description", ""),
                file=coupled,
                suggestion=f"Review {trigger} for necessary changes",
                proposed_fix=fix,
                can_acknowledge=True,
                acknowledge_id=ack_id,
            ))

    return results


def _build_fix_proposal(
    modified_file: str,
    coupled_file: str,
    diff_text: str,
    invariants: dict,
) -> ProposedFix:
    """Build a fix proposal, using function-level co-change data if available."""
    function_co = invariants.get("function_co_changes", {})

    # Find modified functions in the diff
    modified_fns = _extract_modified_functions(modified_file, diff_text)

    predicted_sections = []
    total_confidence = 0.0

    for fn in modified_fns:
        key = f"{modified_file}:{fn}"
        pairs = function_co.get(key, [])
        for pair in pairs:
            if pair.get("file") == coupled_file:
                fn = pair.get("function")
                if fn:
                    predicted_sections.append(fn)
                total_confidence += pair.get("confidence", 0.5)

    if predicted_sections:
        avg = total_confidence / len(predicted_sections)
        return ProposedFix(
            file=coupled_file,
            reason=f"When {modified_file} changes, these sections typically need updates",
            predicted_sections=predicted_sections,
            confidence=round(avg, 2),
        )

    return ProposedFix(
        file=coupled_file,
        reason=f"Historically changes alongside {modified_file}",
        confidence=0.5,
    )


def _extract_modified_functions(filepath: str, diff_text: str) -> List[str]:
    """Extract function names modified in the diff for a specific file."""
    functions = []
    in_file = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            in_file = filepath in line
        elif in_file and line.startswith("@@"):
            # Hunk header may contain function name
            if "def " in line:
                parts = line.split("def ", 1)
                if len(parts) > 1:
                    fn_name = parts[1].split("(")[0].strip()
                    if fn_name:
                        functions.append(fn_name)
        elif in_file and line.startswith("+") and not line.startswith("+++"):
            if "def " in line:
                parts = line.split("def ", 1)
                if len(parts) > 1:
                    fn_name = parts[1].split("(")[0].strip()
                    if fn_name:
                        functions.append(fn_name)

    return list(dict.fromkeys(functions))  # Deduplicate, preserve order


def _ack_id(file_a: str, file_b: str) -> str:
    slug = hashlib.md5(f"{file_a}:{file_b}".encode()).hexdigest()[:6]
    a_short = file_a.replace("/", "_").replace(".", "_")[:20]
    b_short = file_b.replace("/", "_").replace(".", "_")[:20]
    return f"contract_{a_short}_{b_short}_{slug}"
