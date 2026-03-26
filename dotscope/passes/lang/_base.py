"""Base class for tree-sitter language analyzers."""

from abc import ABC, abstractmethod
from typing import Optional

from ...models.core import FileAnalysis


class BaseAnalyzer(ABC):
    """Abstract base for language-specific tree-sitter analyzers.

    Each analyzer holds a lazily-initialized Parser and Language.
    The analyze() method takes filepath + source text and returns
    the same FileAnalysis shape as the Python stdlib ast analyzer.
    """

    @abstractmethod
    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        """Parse source and return FileAnalysis, or None on failure."""
        ...
