"""Convention parser pass: map files to conventions and check rules."""

import os
import re
from typing import Dict, List, Optional

from ..models import ConventionNode, ConventionRule, FileAnalysis


def parse_conventions(
    ast_data: Dict[str, FileAnalysis],
    conventions: List[ConventionRule],
) -> List[ConventionNode]:
    """Apply convention rules against AST data.

    For each file, check if it matches any convention's criteria.
    If matched, check rules and produce a ConventionNode.
    """
    nodes = []
    for file_path, analysis in ast_data.items():
        for rule in conventions:
            if matches_convention(analysis, file_path, rule.match_criteria):
                violations = check_convention_rules(analysis, file_path, rule.rules)
                matched_by = _identify_matching_criteria(
                    analysis, file_path, rule.match_criteria
                )
                nodes.append(ConventionNode(
                    name=rule.name,
                    file_path=file_path,
                    target_name=(
                        analysis.classes[0].name if analysis.classes
                        else os.path.basename(file_path)
                    ),
                    violations=violations,
                    matched_by=matched_by,
                ))
    return nodes


def matches_convention(
    analysis: FileAnalysis,
    file_path: str,
    match_criteria: dict,
) -> bool:
    """Flexible matching with any_of / all_of logic.

    A file matches when:
    - At least one criterion in any_of matches (OR)
    - All criteria in all_of match (AND)
    - If only one block is present, it determines the match alone
    """
    any_of = match_criteria.get("any_of", [])
    all_of = match_criteria.get("all_of", [])

    # Legacy flat format (no any_of/all_of) treated as all_of
    if not any_of and not all_of:
        all_of = [match_criteria] if match_criteria else []

    any_passed = not any_of  # Vacuously true if empty
    for criterion in any_of:
        if _matches_single(analysis, file_path, criterion):
            any_passed = True
            break

    all_passed = True
    for criterion in all_of:
        if not _matches_single(analysis, file_path, criterion):
            all_passed = False
            break

    return any_passed and all_passed


def _matches_single(
    analysis: FileAnalysis,
    file_path: str,
    criterion: dict,
) -> bool:
    """Match a single criterion against a file."""
    for key, value in criterion.items():
        if key == "has_decorator":
            decorators = analysis.decorators_used or []
            if not any(re.search(value, d) for d in decorators):
                return False
        elif key == "file_path":
            if not re.match(value, file_path):
                return False
        elif key == "class_ends_with":
            if not any(c.name.endswith(value) for c in (analysis.classes or [])):
                return False
        elif key == "imports":
            import_modules = _import_modules(analysis)
            if not all(imp in import_modules for imp in value):
                return False
        elif key == "not_imports":
            import_modules = _import_modules(analysis)
            if any(imp in import_modules for imp in value):
                return False
        elif key == "base_class":
            if not any(
                value in (c.bases or [])
                for c in (analysis.classes or [])
            ):
                return False
        else:
            return False  # Unknown criterion, fail safe
    return True


def check_convention_rules(
    analysis: FileAnalysis,
    file_path: str,
    rules: dict,
) -> List[str]:
    """Check a file against its convention's rules."""
    violations = []

    if "prohibited_imports" in rules:
        import_modules = _import_modules(analysis)
        for imp in rules["prohibited_imports"]:
            if imp in import_modules:
                violations.append(f"Prohibited import: {imp}")

    if "required_methods" in rules:
        if analysis.classes:
            methods = set(analysis.classes[0].methods)
            for required in rules["required_methods"]:
                if required not in methods:
                    violations.append(f"Missing required method: {required}")

    if "must_have_matching" in rules:
        pattern = rules["must_have_matching"]
        filename = os.path.splitext(os.path.basename(file_path))[0]
        stem = _extract_stem(filename)

        expected_pattern = (
            pattern
            .replace("{filename}", re.escape(filename))
            .replace("{captured_stem}", re.escape(stem))
        )

        # Search for a matching file in the repo
        repo_root = _guess_repo_root(file_path)
        if repo_root:
            found = False
            for candidate in _walk_files(repo_root):
                if re.match(expected_pattern, candidate):
                    found = True
                    break
            if not found:
                violations.append(
                    f"Missing matching file: {pattern} (resolved: {expected_pattern})"
                )

    return violations


def _identify_matching_criteria(
    analysis: FileAnalysis,
    file_path: str,
    match_criteria: dict,
) -> List[str]:
    """Identify which criteria matched for diagnostics."""
    matched = []
    for block_name in ("any_of", "all_of"):
        for criterion in match_criteria.get(block_name, []):
            for key in criterion:
                if _matches_single(analysis, file_path, {key: criterion[key]}):
                    matched.append(key)
    return matched


def _import_modules(analysis: FileAnalysis) -> set:
    """Extract all import module names from a FileAnalysis."""
    modules = set()
    for imp in (analysis.imports or []):
        if imp.module:
            modules.add(imp.module)
        # Also add individual imported names for granular matching
        for name in (imp.names or []):
            if imp.module:
                modules.add(f"{imp.module}.{name}")
        if imp.raw:
            modules.add(imp.raw)
    return modules


def _extract_stem(filename: str) -> str:
    """Extract stem by stripping common suffixes.

    "user_controller" -> "user"
    "billing_repo" -> "billing"
    "auth_service" -> "auth"
    """
    for suffix in ("_controller", "_service", "_repo", "_repository",
                    "_handler", "_manager", "_factory", "_helper",
                    "_view", "_model", "_test"):
        if filename.endswith(suffix):
            return filename[:-len(suffix)]
    return filename


def _guess_repo_root(file_path: str) -> Optional[str]:
    """Walk up from file_path to find repo root (contains .git or .scopes)."""
    current = os.path.dirname(os.path.abspath(file_path))
    for _ in range(10):
        if os.path.exists(os.path.join(current, ".git")) or \
           os.path.exists(os.path.join(current, ".scopes")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _walk_files(root: str):
    """Yield relative file paths under root."""
    skip = {"__pycache__", ".git", "node_modules", ".tox", ".mypy_cache", "venv", ".venv"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            yield os.path.relpath(os.path.join(dirpath, fn), root)
