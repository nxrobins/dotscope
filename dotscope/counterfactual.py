"""Counterfactual detection: what didn't happen because dotscope was there.

Three sources:
1. Anti-patterns avoided (from near-miss data)
2. Contracts honored (agent modified both sides of a coupled pair)
3. Intents respected (agent didn't violate declared architectural direction)

Only surfaces counterfactuals where the constraint was in the resolve response
the agent received. Coincidences don't count.
"""

import re
from typing import Dict, List, Optional, Set

from .models.state import Counterfactual  # noqa: F401


def compute_counterfactuals(
    constraints_served: List[dict],
    modified_files: Set[str],
    diff_text: str,
    near_misses: Optional[List] = None,
    invariants: Optional[dict] = None,
    intents: Optional[list] = None,
) -> List[Counterfactual]:
    """Compute what dotscope prevented during this session.

    Args:
        constraints_served: Constraints the agent received via resolve_scope
        modified_files: Files the agent actually modified
        diff_text: Combined diff of all commits in this session
        near_misses: Near-miss detections from observation
        invariants: Cached invariants (contracts, stabilities)
        intents: Architectural intents
    """
    results: List[Counterfactual] = []

    # 1. Anti-patterns avoided (from near-miss data)
    if near_misses:
        for nm in near_misses:
            event = nm.get("event", "") if isinstance(nm, dict) else getattr(nm, "event", "")
            scope = nm.get("scope", "") if isinstance(nm, dict) else getattr(nm, "scope", "")
            if event:
                results.append(Counterfactual(
                    type="anti_pattern_avoided",
                    description=event,
                    source=f"{scope} scope context" if scope else "scope context",
                    severity="high",
                ))

    # 2. Contracts honored — agent modified both sides of a coupled pair
    if invariants and modified_files:
        served_contracts = _extract_served_contracts(constraints_served)
        for contract in invariants.get("contracts", []):
            trigger = contract.get("trigger_file", "")
            coupled = contract.get("coupled_file", "")
            confidence = contract.get("confidence", 0.0)

            if confidence < 0.65:
                continue

            # Both modified AND the contract was in the constraints the agent saw
            if (trigger in modified_files
                    and coupled in modified_files
                    and _contract_was_served(trigger, coupled, served_contracts)):
                results.append(Counterfactual(
                    type="contract_honored",
                    description=f"Agent included {coupled} alongside {trigger}",
                    source=f"implicit contract ({confidence:.0%} co-change)",
                    severity="high",
                ))

    # 3. Intents respected — agent didn't violate declared direction
    if intents and modified_files and diff_text:
        served_intents = _extract_served_intents(constraints_served)
        for intent in intents:
            if not isinstance(intent, dict):
                directive = getattr(intent, "directive", "")
                modules = getattr(intent, "modules", [])
            else:
                directive = intent.get("directive", "")
                modules = intent.get("modules", [])

            if directive != "decouple" or len(modules) < 2:
                continue

            # Was this intent served to the agent?
            if not _intent_was_served(directive, modules, served_intents):
                continue

            # Did the agent touch either module without new coupling?
            touched_modules = set()
            for f in modified_files:
                for m in modules:
                    if f.startswith(m):
                        touched_modules.add(m)

            if len(touched_modules) >= 1 and not _has_new_coupling(modules, diff_text):
                mod_str = " and ".join(m.rstrip("/") for m in modules)
                results.append(Counterfactual(
                    type="intent_respected",
                    description=f"Agent avoided new coupling between {mod_str}",
                    source=f"intent: decouple {' '.join(modules)}",
                    severity="medium",
                ))

    return results


def format_counterfactuals_terminal(counterfactuals: List[Counterfactual]) -> str:
    """Format counterfactuals for terminal display."""
    if not counterfactuals:
        return ""

    lines = ["", "  What dotscope prevented:"]
    for cf in counterfactuals:
        lines.append(f"    {cf.description}")
        lines.append(f"      <- {cf.source}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _extract_served_contracts(constraints: List[dict]) -> List[dict]:
    """Extract contract constraints from what was served."""
    return [c for c in constraints if c.get("category") == "contract"]


def _extract_served_intents(constraints: List[dict]) -> List[dict]:
    """Extract intent constraints from what was served."""
    return [c for c in constraints if c.get("category") == "intent"]


def _contract_was_served(
    trigger: str, coupled: str, served: List[dict]
) -> bool:
    """Check if a specific contract was in the served constraints."""
    for c in served:
        msg = c.get("message", "")
        if trigger in msg and coupled in msg:
            return True
        if coupled in msg and trigger in msg:
            return True
    return False


def _intent_was_served(
    directive: str, modules: List[str], served: List[dict]
) -> bool:
    """Check if a specific intent was in the served constraints."""
    for c in served:
        msg = c.get("message", "")
        if directive in msg and any(m.rstrip("/") in msg for m in modules):
            return True
    return False


def _has_new_coupling(modules: List[str], diff_text: str) -> bool:
    """Check if the diff introduces new imports between the listed modules."""
    import_re = re.compile(r'(?:from\s+(\S+)\s+import|import\s+(\S+))')
    current_file = ""

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else ""
        elif line.startswith("+") and not line.startswith("+++"):
            m = import_re.search(line)
            if not m:
                continue
            imported = (m.group(1) or m.group(2) or "").split(".")[0]
            imported_mod = imported + "/"

            file_mod = current_file.split("/")[0] + "/" if "/" in current_file else ""
            if file_mod in modules and imported_mod in modules and file_mod != imported_mod:
                return True

    return False
