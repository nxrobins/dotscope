"""Build and filter constraints for prophylactic injection into resolve_scope."""

import os
from typing import Dict, List, Optional

from .models import Constraint, IntentDirective


def build_constraints(
    scope_dir: str,
    repo_root: str,
    invariants: dict,
    scopes: Dict[str, dict],
    intents: List[IntentDirective],
    graph_hubs: Optional[Dict[str, object]] = None,
    task: Optional[str] = None,
) -> List[Constraint]:
    """Build filtered constraints relevant to a resolved scope.

    Filters to constraints touching the resolved scope's includes.
    If task is provided, ranks by keyword relevance and caps at 5 per category.
    """
    constraints = []

    # 1. Implicit contracts where at least one side is in scope
    for contract in invariants.get("contracts", []):
        trigger = contract.get("trigger_file", "")
        coupled = contract.get("coupled_file", "")
        confidence = contract.get("confidence", 0.0)

        if confidence < 0.65:
            continue

        if _in_scope(trigger, scope_dir) or _in_scope(coupled, scope_dir):
            constraints.append(Constraint(
                category="contract",
                message=(
                    f"If you modify {trigger}, review {coupled} for necessary changes"
                ),
                file=trigger,
                confidence=confidence,
                metadata={"coupled_with": coupled, "co_change_rate": confidence},
            ))

    # 2. Anti-patterns targeting files in scope
    scope_data = scopes.get(scope_dir, {})
    for ap in scope_data.get("anti_patterns", []):
        constraints.append(Constraint(
            category="anti_pattern",
            message=ap.get("message", ""),
            confidence=1.0,
            metadata={
                "pattern": ap.get("pattern", ""),
                "replacement": ap.get("replacement"),
                "scope_files": ap.get("scope_files", []),
            },
        ))

    # 3. Dependency boundaries from graph
    if graph_hubs:
        for hub_file, hub_data in graph_hubs.items():
            if not isinstance(hub_data, dict):
                continue
            if not _in_scope(hub_file, scope_dir):
                continue
            imported_by = hub_data.get("imported_by", [])
            if imported_by:
                # Determine the direction
                hub_module = hub_file.split("/")[0] if "/" in hub_file else ""
                importer_modules = set()
                for imp in imported_by:
                    mod = imp.split("/")[0] if "/" in imp else ""
                    if mod and mod != hub_module:
                        importer_modules.add(mod)
                if importer_modules:
                    constraints.append(Constraint(
                        category="dependency_boundary",
                        message=(
                            f"{hub_module}/ is imported by {', '.join(sorted(importer_modules))}/, "
                            f"not the other way around"
                        ),
                        file=hub_file,
                        confidence=0.9,
                    ))

    # 4. Stability notes
    for filepath, info in invariants.get("file_stabilities", {}).items():
        if not _in_scope(filepath, scope_dir):
            continue
        if info.get("classification") == "stable":
            constraints.append(Constraint(
                category="stability",
                message=(
                    f"{filepath} is stable ({info.get('commit_count', 0)} commits). "
                    f"Large changes deserve extra review."
                ),
                file=filepath,
                confidence=0.8,
            ))

    # 5. Architectural intents mentioning this module
    for intent in intents:
        scope_mod = scope_dir.rstrip("/") + "/"
        if scope_mod in intent.modules or any(
            f.startswith(scope_dir) for f in intent.files
        ):
            constraints.append(Constraint(
                category="intent",
                message=_format_intent(intent),
                confidence=1.0,
                metadata={
                    "directive": intent.directive,
                    "set_by": intent.set_by,
                    "set_at": intent.set_at,
                },
            ))

    # Filter by task relevance if provided
    if task:
        constraints = _rank_by_task(constraints, task)

    # Cap at 5 per category
    return _cap_per_category(constraints, max_per=5)


def _in_scope(filepath: str, scope_dir: str) -> bool:
    """Check if a file falls within a scope directory."""
    return filepath.startswith(scope_dir) or filepath.startswith(scope_dir + "/")


def _format_intent(intent: IntentDirective) -> str:
    """Format an intent as a one-line constraint message."""
    targets = ", ".join(intent.modules + intent.files)
    parts = [f"{intent.directive} {targets}"]
    if intent.reason:
        parts.append(intent.reason)
    if intent.replacement:
        parts.append(f"Use {intent.replacement}")
    return ": ".join(parts)


def _rank_by_task(constraints: List[Constraint], task: str) -> List[Constraint]:
    """Rank constraints by keyword overlap with task description."""
    task_words = set(task.lower().split())

    def relevance(c: Constraint) -> float:
        words = set(c.message.lower().split())
        overlap = task_words & words
        return len(overlap) / max(len(task_words), 1)

    return sorted(constraints, key=relevance, reverse=True)


def _cap_per_category(constraints: List[Constraint], max_per: int = 5) -> List[Constraint]:
    """Cap constraints at max_per per category."""
    counts: Dict[str, int] = {}
    result = []
    for c in constraints:
        count = counts.get(c.category, 0)
        if count < max_per:
            result.append(c)
            counts[c.category] = count + 1
    return result
