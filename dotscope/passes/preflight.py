"""Pre-flight advisory: warnings about what will break before the agent writes code.

Computed at claim time (inside dotscope_claim_scope) and returned alongside
the lock grant. Eliminates the round-trip of discovering violations at
dotscope_check after code is already written.
"""

import os
from typing import Dict, List, Optional


def compute_preflight(
    claimed_files: List[str],
    repo_root: str,
    npmi_index: Optional[Dict[str, Dict[str, float]]] = None,
    network_edges: Optional[Dict[str, Dict[str, list]]] = None,
    conventions: Optional[list] = None,
    swarm_locks: Optional[dict] = None,
    constraints: Optional[list] = None,
) -> dict:
    """Compute advisory warnings for files being claimed.

    Called inside dotscope_claim_scope AFTER the lock is granted,
    BEFORE the response is returned to the agent.
    """
    claimed_set = set(claimed_files)
    warnings = {
        "missing_cochange_partners": [],
        "affected_consumers": [],
        "applicable_conventions": [],
        "lock_conflicts": [],
        "anti_pattern_risks": [],
        "risk_level": "low",
    }

    warning_count = 0

    # 1. Co-change gap detection
    if npmi_index:
        seen_partners = set()
        for f in claimed_files:
            partners = npmi_index.get(f, {})
            for partner, npmi in sorted(partners.items(), key=lambda x: -x[1]):
                if npmi >= 0.5 and partner not in claimed_set and partner not in seen_partners:
                    warnings["missing_cochange_partners"].append({
                        "file": partner,
                        "npmi": round(npmi, 2),
                        "reason": f"Co-change contract with {os.path.basename(f)}",
                    })
                    seen_partners.add(partner)
                    warning_count += 1

    # 2. Consumer impact
    if network_edges:
        for f in claimed_files:
            consumers = network_edges.get(f, {})
            for consumer, eps in consumers.items():
                for ep in eps[:1]:
                    handler = ep.get("handler", "") if isinstance(ep, dict) else ""
                    path = ep.get("path", "") if isinstance(ep, dict) else ""
                    confidence = ep.get("confidence", 1.0) if isinstance(ep, dict) else 1.0
                    warnings["affected_consumers"].append({
                        "consumer": consumer,
                        "endpoint": f"{handler or path}",
                        "confidence": confidence,
                    })
                    warning_count += 1

    # 3. Convention requirements
    if conventions:
        for conv in conventions:
            if isinstance(conv, dict):
                rules = conv.get("rules", {})
                name = conv.get("name", "")
                if rules.get("required_methods"):
                    warnings["applicable_conventions"].append(
                        f"{name} requires: {', '.join(rules['required_methods'])}"
                    )
                if rules.get("allowed_paths"):
                    warnings["applicable_conventions"].append(
                        f"{name}: files must be in {rules['allowed_paths'][0]}"
                    )

    # 4. Lock conflicts (shared/exclusive on blast radius files by other agents)
    if swarm_locks:
        for f in claimed_files:
            status = swarm_locks.get(f, "unlocked")
            if status in ("exclusive_locked", "shared_locked"):
                warnings["lock_conflicts"].append({
                    "file": f,
                    "status": status,
                })
                warning_count += 1

    # 5. Anti-pattern proximity
    if constraints:
        for c in constraints:
            if isinstance(c, dict) and c.get("severity") in ("guard", "GUARD"):
                file_ref = c.get("file", "")
                if file_ref in claimed_set:
                    msg = c.get("message", "")
                    if msg:
                        warnings["anti_pattern_risks"].append(msg)
                        warning_count += 1

    # 6. Risk assessment
    has_lock_conflict = bool(warnings["lock_conflicts"])
    if has_lock_conflict:
        warnings["risk_level"] = "high"
    elif warning_count >= 4:
        warnings["risk_level"] = "high"
    elif warning_count >= 1:
        warnings["risk_level"] = "medium"
    else:
        warnings["risk_level"] = "low"

    return warnings
