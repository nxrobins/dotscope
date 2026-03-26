"""Tree-sitter language analyzers for cross-language compilation.

Dispatches to language-specific analyzers that produce the same
FileAnalysis shape as Python's stdlib ast analyzer.
"""

from typing import Callable, Optional

from ...models.core import FileAnalysis

_analyzers = {}


def _register_analyzers():
    """Register all tree-sitter analyzers. Called once on first use."""
    global _analyzers
    if _analyzers:
        return

    try:
        from .javascript import JavaScriptAnalyzer
        from .go import GoAnalyzer

        _js = JavaScriptAnalyzer()
        _go = GoAnalyzer()

        _analyzers["javascript"] = _js.analyze
        _analyzers["typescript"] = _js.analyze
        _analyzers["go"] = _go.analyze
    except ImportError:
        # tree-sitter not installed — analyzers stay empty, regex fallback
        pass


def get_analyzer(language: str) -> Optional[Callable]:
    """Return a tree-sitter analyzer function for the language, or None."""
    _register_analyzers()
    return _analyzers.get(language.lower())
