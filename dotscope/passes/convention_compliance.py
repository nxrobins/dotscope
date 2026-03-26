"""Convention compliance: track how well conventions are followed."""

from typing import Dict, List

from ..models import ConventionNode, ConventionRule, FileAnalysis
from .convention_parser import matches_convention


def compute_compliance(
    convention: ConventionRule,
    nodes: List[ConventionNode],
    ast_data: Dict[str, FileAnalysis],
) -> float:
    """What percentage of matching files follow all rules?"""
    matching_files = [
        path for path, analysis in ast_data.items()
        if matches_convention(analysis, path, convention.match_criteria)
    ]
    if not matching_files:
        return 1.0

    compliant = sum(
        1 for n in nodes
        if n.name == convention.name and not n.violations
    )
    return compliant / len(matching_files)


def convention_severity(compliance: float) -> str:
    """Map compliance ratio to enforcement severity.

    100-80%: hold (enforced)
    79-50%:  note (warning)
    <50%:    retired (not enforced)
    """
    if compliance >= 0.80:
        return "hold"
    if compliance >= 0.50:
        return "note"
    return "retired"
