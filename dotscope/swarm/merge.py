"""Cross-reference scout findings against codebase structure."""

from collections import defaultdict
from typing import Dict, List, Set


def merge_scout_findings(
    scout_reports: List[dict],
    repo_root: str,
    graph,
    invariants: dict,
) -> dict:
    """Merge parallel scout findings using codebase structure.

    Deterministic structural analysis: convergence detection, hidden
    connection discovery via NPMI, blast radius expansion, and
    scout agreement tiers. No LLM calls.
    """
    # Collect all flagged files with attribution
    file_scouts: Dict[str, List[int]] = defaultdict(list)
    all_files: Set[str] = set()

    for report in scout_reports:
        scout_id = report.get("scout_id", 0)
        for filepath in report.get("flagged_files", []):
            file_scouts[filepath].append(scout_id)
            all_files.add(filepath)

    n_scouts = len(scout_reports)

    # 1. Convergence points: files flagged by 2+ scouts
    convergence_points = []
    for filepath, scouts in file_scouts.items():
        if len(scouts) >= 2:
            convergence_points.append({
                "file": filepath,
                "flagged_by": sorted(scouts),
                "significance": (
                    f"{len(scouts)} independent traces converged on this file"
                ),
            })

    convergence_points.sort(key=lambda c: -len(c["flagged_by"]))

    # 2. Hidden connections: files from different scouts that have
    #    structural relationships (contracts, dependencies)
    hidden_connections = []
    scout_file_groups: Dict[int, Set[str]] = defaultdict(set)
    for report in scout_reports:
        scout_id = report.get("scout_id", 0)
        for filepath in report.get("flagged_files", []):
            scout_file_groups[scout_id].add(filepath)

    # Check NPMI contracts between scout groups
    contracts = invariants.get("contracts", [])
    seen_connections = set()
    for contract in contracts:
        trigger = contract.get("trigger_file", "")
        coupled = contract.get("coupled_file", "")
        confidence = contract.get("confidence", 0)

        if confidence < 0.5:
            continue

        trigger_scouts = set(file_scouts.get(trigger, []))
        coupled_scouts = set(file_scouts.get(coupled, []))

        if (trigger in all_files and coupled in all_files
                and trigger_scouts != coupled_scouts
                and not trigger_scouts & coupled_scouts):
            key = tuple(sorted([trigger, coupled]))
            if key not in seen_connections:
                seen_connections.add(key)
                hidden_connections.append({
                    "file_a": trigger,
                    "file_b": coupled,
                    "relation": "implicit_contract",
                    "confidence": confidence,
                    "note": (
                        f"Co-change rate {confidence:.0%}"
                        f" -- flagged by different scouts"
                    ),
                })

    # Check graph edges between scout groups
    graph_files = graph.files if hasattr(graph, 'files') else {}
    for file_a in all_files:
        node = graph_files.get(file_a)
        if not node:
            continue
        imports = getattr(node, 'imports', []) or []
        for dep in imports:
            if dep in all_files:
                scouts_a = set(file_scouts.get(file_a, []))
                scouts_b = set(file_scouts.get(dep, []))
                if scouts_a and scouts_b and not scouts_a & scouts_b:
                    key = tuple(sorted([file_a, dep]))
                    if key not in seen_connections:
                        seen_connections.add(key)
                        hidden_connections.append({
                            "file_a": file_a,
                            "file_b": dep,
                            "relation": "direct_dependency",
                            "confidence": 1.0,
                            "note": f"{file_a} imports {dep}",
                        })

    # 3. Blast radius: expand via NPMI to find strongly coupled files
    proposed_blast_radius = set(all_files)
    npmi_index = invariants.get("npmi_index", {})
    for filepath in list(all_files):
        coupled_files = npmi_index.get(filepath, {})
        for partner, score in coupled_files.items():
            if score >= 0.8 and partner not in all_files:
                proposed_blast_radius.add(partner)

    # 4. Confidence tiers
    blast_by_confidence: Dict[str, List[str]] = {
        "high": [], "medium": [], "low": [],
    }
    for filepath in proposed_blast_radius:
        scouts = file_scouts.get(filepath, [])
        if len(scouts) >= 2:
            blast_by_confidence["high"].append(filepath)
        elif len(scouts) == 1:
            scout_confidence = next(
                (r.get("confidence", 0.5)
                 for r in scout_reports
                 if r.get("scout_id") in scouts),
                0.5,
            )
            if scout_confidence >= 0.7:
                blast_by_confidence["medium"].append(filepath)
            else:
                blast_by_confidence["low"].append(filepath)
        else:
            # NPMI-expanded files (not flagged by any scout)
            blast_by_confidence["low"].append(filepath)

    for tier in blast_by_confidence.values():
        tier.sort()

    # 5. Scout agreement
    unanimous = sorted(f for f, s in file_scouts.items() if len(s) == n_scouts and n_scouts > 1)
    majority = sorted(
        f for f, s in file_scouts.items()
        if n_scouts > 1 and len(s) > n_scouts / 2 and len(s) < n_scouts
    )
    single = sorted(f for f, s in file_scouts.items() if len(s) == 1)

    return {
        "convergence_points": convergence_points,
        "hidden_connections": hidden_connections,
        "proposed_blast_radius": sorted(proposed_blast_radius),
        "blast_radius_by_confidence": blast_by_confidence,
        "scout_agreement": {
            "unanimous": unanimous,
            "majority": majority,
            "single": single,
        },
    }
