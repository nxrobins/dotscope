"""Convention drift detection: check modified files against conventions."""

from typing import Dict, List

from ..models import CheckCategory, CheckResult, ConventionRule, Severity
from ....models.core import FileAnalysis
from ...convention_compliance import convention_severity
from ...convention_parser import check_convention_rules, matches_convention


def check_conventions(
    modified_files: List[str],
    added_lines: Dict[str, List[str]],
    conventions: List[ConventionRule],
    ast_data: Dict[str, FileAnalysis],
) -> List[CheckResult]:
    """Check modified files for convention drift.

    Returns HOLDs for conventions with >=80% compliance,
    NOTEs for 50-79%, and skips retired conventions.
    """
    results = []

    for filepath in modified_files:
        analysis = ast_data.get(filepath)
        if not analysis:
            continue

        for rule in conventions:
            severity = convention_severity(rule.compliance)
            if severity == "retired":
                continue

            if matches_convention(analysis, filepath, rule.match_criteria):
                violations = check_convention_rules(analysis, filepath, rule.rules)
                for v in violations:
                    results.append(CheckResult(
                        passed=False,
                        category=CheckCategory.CONVENTION,
                        severity=(
                            Severity.NUDGE if severity in ("hold", "nudge")
                            else Severity.NOTE
                        ),
                        message=f"Convention drift: {rule.name}",
                        detail=(
                            f"{filepath} is recognized as a '{rule.name}'.\n"
                            f"Violation: {v}\n"
                            f"Convention compliance: {rule.compliance:.0%}"
                        ),
                        file=filepath,
                        suggestion=rule.description,
                        suggestion=rule.description,
                        source_file="conventions.yaml",
                        source_rule=f"convention:{rule.name}",
                        ))
                    ))

    return results
