"""Shared constants — single source of truth for all modules."""

# Directories to always skip when walking a codebase
SKIP_DIRS = frozenset({
    # Version control
    ".git",
    # Package managers
    "node_modules",
    "vendor",
    # Python
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".eggs",
    ".pytest_cache",
    # Build output
    "dist",
    "build",
    "out",
    "target",
    "bin",
    "obj",
    "artifacts",
    # JS/TS frameworks
    ".next",
    ".nuxt",
    ".output",
    ".parcel-cache",
    # Caches
    "cache",
    ".cache",
    ".gradle",
    ".terraform",
    # Test/coverage output
    "coverage",
    "test-results",
    # dotscope / Claude
    ".dotscope",
    ".claude",
})

# Source file extensions
SOURCE_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".rb", ".java", ".kt",
    ".swift", ".c", ".cpp", ".cs", ".php",
    ".sol",
})

# Extension → language name
LANG_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".sol": "Solidity",
}
