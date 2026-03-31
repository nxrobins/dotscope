"""3-way import resolver using set logic.

Merges imports from two agents using:
  (Ancestor - Removed_A - Removed_B) ∪ Added_A ∪ Added_B

Applies subsumption rules: star imports subsume specific imports
from the same module.
"""

import ast
from typing import List, Set, Tuple


def resolve_imports(
    ancestor_source: str,
    agent_a_source: str,
    agent_b_source: str,
) -> List[str]:
    """3-way merge of import statements.

    Returns the merged list of import lines (as strings).
    """
    ancestor_imports = _extract_import_set(ancestor_source)
    a_imports = _extract_import_set(agent_a_source)
    b_imports = _extract_import_set(agent_b_source)

    removed_a = ancestor_imports - a_imports
    removed_b = ancestor_imports - b_imports
    added_a = a_imports - ancestor_imports
    added_b = b_imports - ancestor_imports

    merged = (ancestor_imports - removed_a - removed_b) | added_a | added_b

    # Subsumption: star import beats specific imports from same module
    merged = _apply_subsumption(merged)

    # Sort: stdlib → third-party → local (simplified: alphabetical by module)
    return sorted(merged, key=_import_sort_key)


def _extract_import_set(source: str) -> Set[str]:
    """Extract all import statements as normalized strings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                key = f"import {alias.name}"
                if alias.asname:
                    key += f" as {alias.asname}"
                imports.add(key)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * node.level
            for alias in node.names:
                if alias.name == "*":
                    imports.add(f"from {prefix}{module} import *")
                else:
                    key = f"from {prefix}{module} import {alias.name}"
                    if alias.asname:
                        key += f" as {alias.asname}"
                    imports.add(key)

    return imports


def _apply_subsumption(imports: Set[str]) -> Set[str]:
    """Star imports subsume specific imports from the same module."""
    star_modules = set()
    for imp in imports:
        if imp.endswith("import *"):
            # "from foo.bar import *" → "foo.bar"
            module = imp.replace("from ", "").replace(" import *", "").strip()
            star_modules.add(module)

    if not star_modules:
        return imports

    result = set()
    for imp in imports:
        # Check if this specific import is subsumed by a star import
        subsumed = False
        for star_mod in star_modules:
            if imp.startswith(f"from {star_mod} import ") and not imp.endswith("import *"):
                subsumed = True
                break
        if not subsumed:
            result.add(imp)

    return result


def _import_sort_key(imp: str) -> Tuple[int, str]:
    """Sort key for imports: stdlib < third-party < local."""
    # Extract the module name
    if imp.startswith("from "):
        parts = imp.split()
        module = parts[1].lstrip(".")
    elif imp.startswith("import "):
        module = imp.split()[1].split(".")[0]
    else:
        module = imp

    # Relative imports go last
    if imp.startswith("from ."):
        return (2, imp)

    # Heuristic: stdlib modules are single words, lowercase
    # This is a simplification — a real implementation would use stdlib list
    return (0, imp)
