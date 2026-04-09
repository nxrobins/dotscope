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
    """Return an empty baseline for spatial conventions.

    Dotscope is a universal physics engine spanning Rust, Java, Typescript, and Python.
    Dictating web-framework specific layouts (like REST Controllers) artificially biases 
    codebase architectures, violating the clean-room abstraction of the engine.
    """
    return []
