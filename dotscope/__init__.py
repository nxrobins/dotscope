"""dotscope - Directory-scoped context boundaries for AI coding agents."""

import importlib

__version__ = "1.7.7"


_LEGACY_SUBMODULES = frozenset({
    "absorber",
    "assertions",
    "bench",
    "composer",
    "constants",
    "context",
    "counterfactual",
    "debug",
    "discovery",
    "explain",
    "formatter",
    "health",
    "ignore",
    "ingest",
    "intent",
    "lessons",
    "matcher",
    "parser",
    "refresh",
    "regression",
    "resolver",
    "runtime_overlay",
    "scanner",
    "textio",
    "utility",
    "visibility",
})


def __getattr__(name: str):
    """Lazily expose backward-compatible top-level modules."""
    if name not in _LEGACY_SUBMODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = importlib.import_module(f".{name}", __name__)
    globals()[name] = module
    return module


def __dir__():
    """Expose legacy compat submodules during package introspection."""
    return sorted(set(globals()) | _LEGACY_SUBMODULES)
