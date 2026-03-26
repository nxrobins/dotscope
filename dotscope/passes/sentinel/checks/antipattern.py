"""Anti-pattern check: diff introduces patterns a scope prohibits."""

import re
from typing import Dict, List, Optional

from ..models import CheckCategory, CheckResult, ProposedFix, Severity


def check_antipatterns(
    added_lines: Dict[str, List[str]],
    scopes: Dict[str, dict],
    repo_root: str,
) -> List[CheckResult]:
    """Check added lines against anti_patterns defined in scope files.

    Each scope may have:
        anti_patterns:
          - pattern: "\\.delete\\(\\)"
            replacement: ".deactivate()"
            scope_files: ["models/user.py"]
            message: "Use .deactivate() instead of .delete() on User"
    """
    results = []

    for scope_dir, scope_data in scopes.items():
        patterns = scope_data.get("anti_patterns", [])
        if not patterns:
            continue

        for ap in patterns:
            pattern_str = ap.get("pattern", "")
            if not pattern_str:
                continue

            try:
                regex = re.compile(pattern_str)
            except re.error:
                continue

            scope_files = ap.get("scope_files", [])
            message = ap.get("message", f"Matches prohibited pattern: {pattern_str}")
            replacement = ap.get("replacement")

            for filepath, lines in added_lines.items():
                # If scope_files is specified, only check those files
                if scope_files and not any(filepath.endswith(sf) or filepath == sf for sf in scope_files):
                    continue

                # Check if file is in this scope's directory
                if not scope_files and not filepath.startswith(scope_dir):
                    continue

                from ..line_filter import strip_comments_and_strings

                for line_text in lines:
                    code_only = strip_comments_and_strings(line_text)
                    if not code_only.strip():
                        continue
                    if regex.search(code_only):
                        fix = None
                        if replacement:
                            fixed = regex.sub(replacement, line_text)
                            fix = ProposedFix(
                                file=filepath,
                                reason=message,
                                proposed_diff=f"-{line_text.strip()}\n+{fixed.strip()}",
                                confidence=1.0,
                            )

                        results.append(CheckResult(
                            passed=False,
                            category=CheckCategory.ANTIPATTERN,
                            severity=Severity.NUDGE,
                            message=message,
                            detail=f"Pattern: {pattern_str} in {filepath}",
                            file=filepath,
                            suggestion=f"Use {replacement}" if replacement else "See scope context",
                            proposed_fix=fix,
                            can_acknowledge=True,
                            acknowledge_id=f"antipattern_{pattern_str[:20].replace('.', '_')}",
                        ))
                        break  # One match per file per pattern is enough

    return results
