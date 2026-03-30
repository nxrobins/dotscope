"""Prescriptive voice defaults for new codebases.

Applied when detect_codebase_maturity returns "new" (<10 files or
<20 commits). Opinionated starting point that the developer can relax.
"""

from typing import List

from ..models.intent import ConventionRule, DiscoveredVoice


def prescriptive_defaults() -> DiscoveredVoice:
    """Return strict voice config for a greenfield project."""
    return DiscoveredVoice(
        mode="prescriptive",
        rules={
            "typing": "Type hints on all function signatures. Return types always specified.",
            "docstrings": "Google style. Imperative mood. One-line if the name explains it.",
            "error_handling": "Domain exceptions. No bare excepts. Let unexpected errors propagate.",
            "structure": "Early returns over nested conditionals. Guard clauses at the top.",
            "density": "Concise. Comprehensions where readable. No filler variables.",
            "comments": "Comments explain why, not what.",
            "imports": "stdlib first, third-party second, local third. One import per line.",
        },
        stats={},
        enforce={
            "bare_excepts": "hold",
            "missing_type_hints": "note",
        },
    )


def prescriptive_spatial_conventions() -> List[ConventionRule]:
    """Return DDD spatial conventions for a greenfield project.

    Agents building from scratch get a clean Domain-Driven Design scaffold
    so files land in the right place from the very first commit.
    """
    return [
        ConventionRule(
            name="Domain Model",
            source="prescriptive",
            match_criteria={"any_of": [{"base_class": "BaseModel"}]},
            rules={"allowed_paths": [r"domains/[^/]+/models/.*\.py"]},
            description="Domain models live under domains/<module>/models/",
        ),
        ConventionRule(
            name="REST Controller",
            source="prescriptive",
            match_criteria={"any_of": [{"has_decorator": "router"}]},
            rules={"allowed_paths": [r"domains/[^/]+/api/.*\.py"]},
            description="Route handlers live under domains/<module>/api/",
        ),
        ConventionRule(
            name="Service Layer",
            source="prescriptive",
            match_criteria={"any_of": [{"file_path": r".*_service\.py"}]},
            rules={"allowed_paths": [r"domains/[^/]+/services/.*\.py"]},
            description="Service files live under domains/<module>/services/",
        ),
        ConventionRule(
            name="Repository",
            source="prescriptive",
            match_criteria={"any_of": [{"file_path": r".*_repo\.py"}]},
            rules={"allowed_paths": [r"domains/[^/]+/repos/.*\.py"]},
            description="Repository files live under domains/<module>/repos/",
        ),
    ]
