"""Build and filter constraints for prophylactic injection into resolve_scope."""

import os
from typing import Dict, List, Optional

from .models import Constraint, ConventionRule, IntentDirective


def build_constraints(
    scope_dir: str,
    repo_root: str,
    invariants: dict,
    scopes: Dict[str, dict],
    intents: List[IntentDirective],
    graph_hubs: Optional[Dict[str, object]] = None,
    task: Optional[str] = None,
    conventions: Optional[List[ConventionRule]] = None,
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

    # 6. Convention blueprints matching this scope
    for conv in (conventions or []):
        if conv.compliance < 0.50:
            continue  # Skip retired conventions
        rules_summary = []
        if conv.rules.get("prohibited_imports"):
            rules_summary.append(
                f"Do not import: {', '.join(conv.rules['prohibited_imports'])}"
            )
        if conv.rules.get("required_methods"):
            rules_summary.append(
                f"Must implement: {', '.join(conv.rules['required_methods'])}"
            )
        if rules_summary:
            constraints.append(Constraint(
                category="convention",
                message=(
                    f"Convention '{conv.name}': {'; '.join(rules_summary)}"
                ),
                confidence=conv.compliance,
                metadata={
                    "convention": conv.name,
                    "description": conv.description,
                    "compliance": conv.compliance,
                },
            ))

    # Filter by task relevance if provided
    if task:
        constraints = _rank_by_task(constraints, task)

    # Cap at 5 per category
    return _cap_per_category(constraints, max_per=5)


def build_routing_guidance(
    scope_dir: str,
    conventions: Optional[List[ConventionRule]] = None,
    voice_config: Optional[dict] = None,
    repo_root: Optional[str] = None,
) -> List[Constraint]:
    """Build positive-frame routing guidance: what patterns apply here.

    Constraints tell agents what NOT to do. Routing tells agents what TO do.
    This is the bowling bumper: the agent reads it and writes code that
    already follows the rules.
    """
    guidance: List[Constraint] = []

    for conv in (conventions or []):
        if conv.compliance < 0.50:
            continue

        rules = conv.rules or {}
        rules_summary = _convention_rules_summary(rules)

        # Existing-file routing: what convention files in this scope follow
        parts = [f"Files here follow the '{conv.name}' convention"]
        if conv.description:
            parts.append(conv.description)
        if rules_summary:
            parts.extend(rules_summary)
        guidance.append(Constraint(
            category="routing",
            message=". ".join(parts),
            confidence=conv.compliance,
            metadata={"convention": conv.name, "type": "convention_blueprint"},
        ))

        # Gap 1: Path-first routing for new files
        # If convention has file_path match criteria, inject guidance for
        # files that don't exist yet
        for criteria_list in (
            conv.match_criteria.get("any_of", []),
            conv.match_criteria.get("all_of", []),
        ):
            for criterion in criteria_list:
                if isinstance(criterion, dict) and "file_path" in criterion:
                    pattern = criterion["file_path"]
                    parts_new = [
                        f"New files matching pattern {pattern} "
                        f"should follow '{conv.name}' convention"
                    ]
                    if rules_summary:
                        parts_new.extend(rules_summary)
                    guidance.append(Constraint(
                        category="routing",
                        message=". ".join(parts_new),
                        confidence=conv.compliance,
                        metadata={
                            "convention": conv.name,
                            "type": "path_pattern",
                            "pattern": pattern,
                        },
                    ))

    # Voice guidance
    if voice_config and voice_config.get("mode"):
        voice_parts = []
        for key in ("typing", "docstrings", "error_handling", "structure", "density"):
            val = voice_config.get(key)
            if val and isinstance(val, str):
                voice_parts.append(val.strip().split("\n")[0])
        if voice_parts:
            guidance.append(Constraint(
                category="routing",
                message="Code style: " + ". ".join(voice_parts),
                confidence=0.9,
                metadata={"type": "voice"},
            ))

    # Gap 6: Learned routing from observations
    if repo_root:
        learned = _learned_routing(scope_dir, repo_root)
        guidance.extend(learned)

    # Deduplicate: if two conventions match the same path pattern,
    # keep the one with higher compliance
    return _deduplicate_routing(guidance)


def build_adjacent_routing(
    scope_dir: str,
    graph_hubs: Optional[Dict[str, object]] = None,
    all_scopes: Optional[Dict[str, dict]] = None,
    conventions: Optional[List[ConventionRule]] = None,
) -> List[Constraint]:
    """Gap 2: Routing for scopes the agent is likely to touch next.

    When resolving scope X, check which other scopes X's files import from.
    Include a compact routing summary for those adjacent scopes.
    """
    if not graph_hubs or not all_scopes:
        return []

    adjacent_modules: set = set()
    scope_mod = scope_dir.rstrip("/")

    for hub_file, hub_data in graph_hubs.items():
        if not isinstance(hub_data, dict):
            continue
        if not _in_scope(hub_file, scope_dir):
            continue
        for imp in hub_data.get("imported_by", []):
            mod = imp.split("/")[0] if "/" in imp else ""
            if mod and mod != scope_mod:
                adjacent_modules.add(mod)
        for dep in hub_data.get("imports", []):
            mod = dep.split("/")[0] if "/" in dep else ""
            if mod and mod != scope_mod:
                adjacent_modules.add(mod)

    guidance: List[Constraint] = []
    for mod in sorted(adjacent_modules):
        scope_data = all_scopes.get(mod, {})
        desc = scope_data.get("description", "")
        parts = [f"Adjacent scope: {mod}/"]
        if desc:
            parts.append(desc)

        # Find conventions that apply to this adjacent scope
        for conv in (conventions or []):
            if conv.compliance < 0.50:
                continue
            for criteria_list in (
                conv.match_criteria.get("any_of", []),
                conv.match_criteria.get("all_of", []),
            ):
                for criterion in criteria_list:
                    if isinstance(criterion, dict):
                        fp = criterion.get("file_path", "")
                        if fp and mod in fp:
                            rules_summary = _convention_rules_summary(conv.rules or {})
                            parts.append(f"Convention '{conv.name}'")
                            parts.extend(rules_summary)
                            break

        if len(parts) > 1:  # Only include if we have something beyond the name
            guidance.append(Constraint(
                category="routing_adjacent",
                message=". ".join(parts),
                confidence=0.7,
                metadata={"adjacent_scope": mod, "type": "adjacent"},
            ))

    return guidance[:5]  # Cap at 5 adjacent scopes


def match_conventions_by_path(
    filepath: str,
    conventions: List[ConventionRule],
) -> List[dict]:
    """Gap 5: File creation advisor. Match conventions by path only (no AST needed).

    Returns matching conventions with their rules for a file that may not exist yet.
    """
    import re
    matches = []
    for conv in conventions:
        if conv.compliance < 0.50:
            continue
        for criteria_list in (
            conv.match_criteria.get("any_of", []),
            conv.match_criteria.get("all_of", []),
        ):
            for criterion in criteria_list:
                if not isinstance(criterion, dict):
                    continue
                fp = criterion.get("file_path", "")
                if fp:
                    try:
                        if re.search(fp, filepath):
                            matches.append({
                                "convention": conv.name,
                                "description": conv.description,
                                "rules": conv.rules,
                                "compliance": conv.compliance,
                                "matched_by": f"file_path: {fp}",
                            })
                    except re.error:
                        pass
                # Also match class_ends_with against filename
                suffix = criterion.get("class_ends_with", "")
                if suffix and suffix.lower() in filepath.lower():
                    matches.append({
                        "convention": conv.name,
                        "description": conv.description,
                        "rules": conv.rules,
                        "compliance": conv.compliance,
                        "matched_by": f"class_ends_with: {suffix} (from filename)",
                    })
    # Deduplicate by convention name
    seen = set()
    result = []
    for m in matches:
        if m["convention"] not in seen:
            seen.add(m["convention"])
            result.append(m)
    return result


def _deduplicate_routing(guidance: List[Constraint]) -> List[Constraint]:
    """Deduplicate routing by (convention, type), keeping highest compliance.

    If two conventions with the same name AND same type produce guidance,
    keep the one with higher compliance. Different types (blueprint vs
    path_pattern) for the same convention are both kept.
    """
    best: Dict[tuple, Constraint] = {}
    non_convention: List[Constraint] = []

    for g in guidance:
        conv_name = g.metadata.get("convention")
        if not conv_name:
            non_convention.append(g)
            continue
        gtype = g.metadata.get("type", "")
        key = (conv_name, gtype)
        existing = best.get(key)
        if existing is None or g.confidence > existing.confidence:
            best[key] = g

    return list(best.values()) + non_convention


def _convention_rules_summary(rules: dict) -> List[str]:
    """Build a compact rules summary list for a convention."""
    parts = []
    if rules.get("required_methods"):
        parts.append(f"Implement: {', '.join(rules['required_methods'])}")
    if rules.get("prohibited_imports"):
        parts.append(f"Do not import: {', '.join(rules['prohibited_imports'])}")
    return parts


def _learned_routing(scope_dir: str, repo_root: str) -> List[Constraint]:
    """Gap 6: Inject routing from observation data.

    If agents repeatedly needed file X when resolving scope Y but X isn't
    in Y's includes, mention it as routing guidance.
    """
    import json
    scores_path = os.path.join(repo_root, ".dotscope", "utility_scores.json")
    if not os.path.exists(scores_path):
        return []

    try:
        with open(scores_path, "r", encoding="utf-8") as f:
            scores = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    guidance = []
    scope_scores = scores.get(scope_dir, scores.get(scope_dir.rstrip("/"), {}))
    if not isinstance(scope_scores, dict):
        return []

    # Files with high utility that aren't in this scope
    for filepath, score in sorted(scope_scores.items(), key=lambda x: x[1], reverse=True):
        if isinstance(score, (int, float)) and score >= 3.0:
            if not _in_scope(filepath, scope_dir):
                guidance.append(Constraint(
                    category="routing",
                    message=(
                        f"Agents frequently need {filepath} when working in {scope_dir} "
                        f"(utility score: {score:.1f})"
                    ),
                    confidence=min(score / 5.0, 0.95),
                    metadata={"type": "learned", "file": filepath, "score": score},
                ))
        if len(guidance) >= 3:
            break

    return guidance


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
