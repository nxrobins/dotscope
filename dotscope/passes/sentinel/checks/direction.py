"""Dependency direction check: new imports that reverse established flow."""

import re
from typing import Dict, List, Optional

from ..models import CheckCategory, CheckResult, Severity


def check_dependency_direction(
    added_lines: Dict[str, List[str]],
    graph_hubs: Dict[str, object],
    scopes: Dict[str, dict],
) -> List[CheckResult]:
    """Detect new imports that reverse established dependency direction.

    If models/ is imported BY api/ (not the other way around),
    a new 'from api import ...' in models/ is a direction reversal.
    """
    results = []

    # Build direction map from graph hubs: module → set of modules it imports
    import_directions = {}  # type: Dict[str, set]
    for hub_file, hub_data in graph_hubs.items():
        if isinstance(hub_data, dict):
            imported_by = hub_data.get("imported_by", [])
            module = hub_file.split("/")[0] if "/" in hub_file else ""
            if module:
                for importer in imported_by:
                    imp_module = importer.split("/")[0] if "/" in importer else ""
                    if imp_module and imp_module != module:
                        import_directions.setdefault(imp_module, set()).add(module)

    if not import_directions:
        return results

    import_re = re.compile(
        r'(?:from\s+(\S+)\s+import|import\s+(\S+))'
    )

    for filepath, lines in added_lines.items():
        file_module = filepath.split("/")[0] if "/" in filepath else ""
        if not file_module:
            continue

        for line_text in lines:
            m = import_re.search(line_text)
            if not m:
                continue

            imported = m.group(1) or m.group(2) or ""
            imported_module = imported.split(".")[0]

            if not imported_module or imported_module == file_module:
                continue

            # Check: does imported_module normally import file_module?
            # If so, this new import reverses the established direction.
            if file_module in import_directions.get(imported_module, set()):
                results.append(CheckResult(
                    passed=False,
                    category=CheckCategory.DIRECTION,
                    severity=Severity.NOTE,
                    message=(
                        f"New import in {filepath}: {imported_module} "
                        f"is imported BY {file_module}, not the other way around"
                    ),
                    detail=f"{file_module}/ normally does not import from {imported_module}/",
                    file=filepath,
                    source_file="heuristic",
                    source_rule="dependency_direction",
                ))

    return results
