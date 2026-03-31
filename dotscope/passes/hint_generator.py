"""Action hint generator: derive imperative directives from constraints and locks.

Converts structured constraint data into short, natural-language directives
that agents act on without interpretation. Maximum 5 hints per response.
Priority order determines which survive truncation: locks first (external
mutable state, not recoverable), then co-change, then network, then
anti-patterns, then conventions.
"""

from typing import Dict, List, Optional, Set

from ..models import ResolvedScope

MAX_HINTS = 5


def generate_action_hints(
    resolved: ResolvedScope,
    npmi_index: Optional[Dict[str, Dict[str, float]]] = None,
    network_edges: Optional[Dict[str, Dict[str, list]]] = None,
    constraints: Optional[list] = None,
    conventions: Optional[list] = None,
) -> List[str]:
    """Derive imperative action hints from constraints, locks, and routing.

    Rules (evaluated in priority order, deduplicated):
    1. Exclusive locks on abstractions (HARD BLOCKER)
    2. Shared locks (WARNING)
    3. Co-change contracts
    4. Network contract consumers
    5. Anti-pattern proximity
    6. Convention reminders
    """
    hints: List[str] = []
    seen_files: Set[str] = set()

    file_set = set(resolved.files)

    # Priority 1: Exclusive locks on flattened abstractions
    for name, ab in resolved.flattened_abstractions.items():
        if isinstance(ab, dict) and ab.get("lock_status") == "exclusive_locked":
            origin = ab.get("origin_file", "")
            hint = (
                f"{name}() in {origin} is locked by another agent. "
                f"Do not modify its signature."
            )
            if hint not in hints:
                hints.append(hint)
                seen_files.add(origin)

    # Priority 2: Shared locks
    for name, ab in resolved.flattened_abstractions.items():
        if isinstance(ab, dict) and ab.get("lock_status") == "shared_locked":
            origin = ab.get("origin_file", "")
            if origin not in seen_files:
                hint = (
                    f"{origin} has a shared lock. Another agent has nearby work. "
                    f"Verify your changes don't conflict."
                )
                hints.append(hint)
                seen_files.add(origin)

    # Priority 3: Co-change contracts
    if npmi_index:
        for f in resolved.files:
            partners = npmi_index.get(f, {})
            for partner, npmi in sorted(partners.items(), key=lambda x: -x[1]):
                if npmi >= 0.5 and partner not in file_set and partner not in seen_files:
                    import os
                    hint = (
                        f"{os.path.basename(f)} has a co-change contract with "
                        f"{os.path.basename(partner)} (NPMI {npmi:.2f}). "
                        f"Include both in your changes."
                    )
                    if hint not in hints:
                        hints.append(hint)
                        seen_files.add(partner)

    # Priority 4: Network contract consumers
    if network_edges:
        for f in resolved.files:
            consumers = network_edges.get(f, {})
            if consumers:
                count = len(consumers)
                endpoints = []
                for consumer, eps in consumers.items():
                    for ep in eps[:1]:
                        handler = ep.get("handler", "") if isinstance(ep, dict) else ""
                        if handler:
                            endpoints.append(handler)
                ep_label = endpoints[0] if endpoints else f
                hint = (
                    f"{ep_label} has {count} frontend consumer(s). "
                    f"Changes to request/response schema require consumer updates."
                )
                if hint not in hints:
                    hints.append(hint)

    # Priority 5: Anti-pattern proximity
    if constraints:
        for c in constraints:
            if isinstance(c, dict) and c.get("severity") in ("guard", "GUARD"):
                msg = c.get("message", "")
                if msg and msg not in hints:
                    hints.append(msg)

    # Priority 6: Convention reminders
    if conventions:
        for conv in conventions:
            if isinstance(conv, dict):
                name = conv.get("name", "")
                rules = conv.get("rules", {})
                if rules.get("required_methods"):
                    hint = (
                        f"{name} convention requires: "
                        f"{', '.join(rules['required_methods'])}."
                    )
                    if hint not in hints:
                        hints.append(hint)
                if rules.get("allowed_paths"):
                    hint = (
                        f"{name}: files must be in {rules['allowed_paths'][0]}."
                    )
                    if hint not in hints:
                        hints.append(hint)

    # Truncate to MAX_HINTS, preserving priority order
    return hints[:MAX_HINTS]
