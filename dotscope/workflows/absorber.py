"""Documentation absorber: extract architectural knowledge from existing docs.

Scans for and extracts knowledge from:
- README.md, ARCHITECTURE.md, CONTRIBUTING.md
- Docstrings (module-level and class-level)
- Inline comments with signals: NOTE, HACK, TODO, WARNING, FIXME, XXX, IMPORTANT
- Type hints and function signatures (contract-like information)
"""


import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..engine.constants import SKIP_DIRS, SOURCE_EXTS


@dataclass
class DocFragment:
    """A fragment of documentation extracted from the codebase."""
    source: str  # File path relative to root
    content: str  # The text content
    kind: str  # "readme", "docstring", "comment", "architecture"
    relevance_module: str  # Which module this is relevant to (top-level dir)
    priority: int = 0  # Higher = more important (warnings > notes > general)


@dataclass
class AbsorptionResult:
    """All documentation fragments found in a codebase."""
    fragments: List[DocFragment] = field(default_factory=list)
    by_module: Dict[str, List[DocFragment]] = field(default_factory=dict)
    doc_files_found: List[str] = field(default_factory=list)

    def for_module(self, module: str) -> List[DocFragment]:
        """Get all fragments relevant to a module, sorted by priority."""
        frags = self.by_module.get(module, [])
        return sorted(frags, key=lambda f: -f.priority)

    def synthesize_context(self, module: str, max_chars: int = 2000) -> str:
        """Synthesize a clean context string from fragments for a module.

        Groups fragments by kind in order: architecture > docstrings > comments > readme.
        Avoids noisy filepath prefixes — agents need the knowledge, not the source location.
        """
        frags = self.for_module(module)
        if not frags:
            return ""

        # Group by kind, ordered by usefulness to agents
        kind_order = {"architecture": 0, "docstring": 1, "comment": 2, "readme": 3}
        grouped: dict[str, list] = {}
        for frag in frags:
            grouped.setdefault(frag.kind, []).append(frag)

        parts = []
        total = 0
        for kind in sorted(grouped.keys(), key=lambda k: kind_order.get(k, 99)):
            for frag in grouped[kind]:
                # Clean the content — strip filepath prefixes
                content = frag.content
                if content.startswith("[") and "] " in content:
                    content = content.split("] ", 1)[1]
                # Skip very short fragments (noise)
                if len(content.strip()) < 10:
                    continue
                if total + len(content) > max_chars:
                    break
                parts.append(content)
                total += len(content)

        return "\n".join(parts)


# Doc files to look for (in priority order)
_DOC_FILES = [
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "README.md",
    "DESIGN.md",
    "AGENTS.md",
    "docs/architecture.md",
    "docs/design.md",
    "docs/contributing.md",
]

# Comment signal patterns and their priorities.
# Use (.+?) non-greedy to avoid capturing trailing inline comments.
_SIGNAL_PATTERN = r"\s*:?\s*(.+?)(?:\s+#.*|\s+//.*)?$"
_COMMENT_SIGNALS = [
    (re.compile(r"#\s*(WARNING|DANGER|CRITICAL)" + _SIGNAL_PATTERN, re.I), 10),
    (re.compile(r"#\s*(IMPORTANT|INVARIANT)" + _SIGNAL_PATTERN, re.I), 9),
    (re.compile(r"#\s*(HACK|WORKAROUND)" + _SIGNAL_PATTERN, re.I), 8),
    (re.compile(r"#\s*(NOTE|NB)" + _SIGNAL_PATTERN, re.I), 6),
    (re.compile(r"#\s*(TODO|FIXME|XXX)" + _SIGNAL_PATTERN, re.I), 5),
    (re.compile(r"//\s*(WARNING|DANGER|CRITICAL)" + _SIGNAL_PATTERN, re.I), 10),
    (re.compile(r"//\s*(IMPORTANT|INVARIANT)" + _SIGNAL_PATTERN, re.I), 9),
    (re.compile(r"//\s*(HACK|WORKAROUND)" + _SIGNAL_PATTERN, re.I), 8),
    (re.compile(r"//\s*(NOTE|NB)" + _SIGNAL_PATTERN, re.I), 6),
    (re.compile(r"//\s*(TODO|FIXME|XXX)" + _SIGNAL_PATTERN, re.I), 5),
]


def absorb_docs(root: str, apis: Optional[Dict] = None) -> AbsorptionResult:
    """Scan a codebase and absorb all architectural documentation.

    Collects fragments from doc files, docstrings, signal comments,
    and AST-extracted API surfaces, then clusters by module.

    Args:
        root: Repository root
        apis: Optional dict of {rel_path: ModuleAPI} from AST analysis.
              If provided, uses AST data for docstrings and API surfaces.
    """
    root = os.path.abspath(root)
    result = AbsorptionResult()

    _absorb_doc_files(root, result)

    if apis:
        _absorb_from_ast(root, apis, result)
    else:
        _absorb_docstrings(root, result)

    _absorb_signal_comments(root, result)

    # 4. Cluster fragments by module
    for frag in result.fragments:
        if frag.relevance_module not in result.by_module:
            result.by_module[frag.relevance_module] = []
        result.by_module[frag.relevance_module].append(frag)

    return result


def _absorb_from_ast(root: str, apis: Dict, result: AbsorptionResult) -> None:
    """Extract documentation from AST-analyzed modules."""
    for rel_path, api in apis.items():
        parts = rel_path.split(os.sep)
        module = parts[0] if len(parts) > 1 else "_root"

        # Module docstring (from AST, more reliable than regex)
        if api.docstring and len(api.docstring) > 20:
            result.fragments.append(DocFragment(
                source=rel_path,
                content=api.docstring,
                kind="docstring",
                relevance_module=module,
                priority=4,
            ))

        # Public API surface
        public_fns = [f for f in api.functions if f.is_public]
        public_classes = [c for c in api.classes if c.is_public]

        if public_fns or public_classes:
            api_lines = []
            for cls in public_classes:
                bases = f"({', '.join(cls.bases)})" if cls.bases else ""
                decorators = ", ".join(f"@{d}" for d in cls.decorators[:3])
                dec_str = f" [{decorators}]" if decorators else ""
                methods = [m for m in cls.methods if not m.startswith("_")]
                api_lines.append(
                    f"{cls.name}{bases}{dec_str} — {len(methods)} public method(s)"
                )

            for fn in public_fns:
                params = ", ".join(fn.params[:5])
                ret = f" -> {fn.return_type}" if fn.return_type else ""
                decorators = ", ".join(f"@{d}" for d in fn.decorators[:2])
                dec_str = f" [{decorators}]" if decorators else ""
                api_lines.append(f"{fn.name}({params}){ret}{dec_str}")

            if api_lines:
                content = "\n".join(api_lines)
                result.fragments.append(DocFragment(
                    source=rel_path,
                    content=content,
                    kind="api_surface",
                    relevance_module=module,
                    priority=8,
                ))

        # Class hierarchies
        for cls in public_classes:
            if cls.bases:
                result.fragments.append(DocFragment(
                    source=rel_path,
                    content=f"{cls.name} inherits from {', '.join(cls.bases)}",
                    kind="class_hierarchy",
                    relevance_module=module,
                    priority=7,
                ))

        # Decorator patterns (framework-significant ones)
        significant_decorators = {"dataclass", "abstractmethod", "property",
                                  "staticmethod", "classmethod", "app.route",
                                  "pytest.fixture", "lru_cache", "cached_property"}
        for fn in api.functions:
            for dec in fn.decorators:
                if any(sig in dec for sig in significant_decorators):
                    result.fragments.append(DocFragment(
                        source=rel_path,
                        content=f"@{dec} on {fn.name}",
                        kind="decorator_pattern",
                        relevance_module=module,
                        priority=6,
                    ))


def _absorb_doc_files(root: str, result: AbsorptionResult) -> None:
    """Find and absorb documentation files."""
    # Top-level docs
    for doc_name in _DOC_FILES:
        doc_path = os.path.join(root, doc_name)
        if os.path.isfile(doc_path):
            result.doc_files_found.append(doc_name)
            content = _read_file(doc_path)
            if content:
                # Extract sections and assign to relevant modules
                sections = _split_markdown_sections(content)
                for heading, body in sections:
                    module = _guess_module_from_text(heading + " " + body, root)
                    result.fragments.append(DocFragment(
                        source=doc_name,
                        content=f"From {doc_name} — {heading}:\n{body[:500]}",
                        kind="readme" if "README" in doc_name else "architecture",
                        relevance_module=module or "_root",
                        priority=7 if "ARCHITECTURE" in doc_name.upper() else 5,
                    ))

    # Module-level docs (e.g., auth/README.md)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            continue

        for fn in filenames:
            if fn.upper() in ("README.MD", "ARCHITECTURE.MD", "DESIGN.MD"):
                rel_path = os.path.join(rel_dir, fn)
                full_path = os.path.join(dirpath, fn)
                content = _read_file(full_path)
                if content:
                    module = rel_dir.split(os.sep)[0]
                    result.doc_files_found.append(rel_path)
                    result.fragments.append(DocFragment(
                        source=rel_path,
                        content=content[:1000],
                        kind="readme",
                        relevance_module=module,
                        priority=8,  # Module-specific docs are high priority
                    ))


def _absorb_docstrings(root: str, result: AbsorptionResult) -> None:
    """Extract module-level and class-level docstrings from Python files."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fn in filenames:
            if not fn.endswith(".py"):
                continue

            rel_path = os.path.relpath(os.path.join(dirpath, fn), root)
            parts = rel_path.split(os.sep)
            module = parts[0] if len(parts) > 1 else "_root"

            full_path = os.path.join(dirpath, fn)
            docstring = _extract_module_docstring(full_path)
            if docstring and len(docstring) > 20:
                result.fragments.append(DocFragment(
                    source=rel_path,
                    content=docstring,
                    kind="docstring",
                    relevance_module=module,
                    priority=4,
                ))


def _absorb_signal_comments(root: str, result: AbsorptionResult) -> None:
    """Find comments with signal words (WARNING, NOTE, HACK, TODO, etc.)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SOURCE_EXTS:
                continue

            rel_path = os.path.relpath(os.path.join(dirpath, fn), root)
            parts = rel_path.split(os.sep)
            module = parts[0] if len(parts) > 1 else "_root"

            full_path = os.path.join(dirpath, fn)
            signals = _extract_signal_comments(full_path)
            for comment_text, priority in signals:
                result.fragments.append(DocFragment(
                    source=rel_path,
                    content=comment_text,
                    kind="comment",
                    relevance_module=module,
                    priority=priority,
                ))


def _extract_module_docstring(filepath: str) -> Optional[str]:
    """Extract the module-level docstring from a Python file."""
    content = _read_file(filepath)
    if not content:
        return None

    # Match triple-quoted string at the start of the file (after optional comments/encoding)
    m = re.match(
        r'^(?:\s*#[^\n]*\n)*\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')',
        content,
        re.DOTALL,
    )
    if m:
        return (m.group(1) or m.group(2) or "").strip()
    return None


def _extract_signal_comments(filepath: str) -> List[Tuple[str, int]]:
    """Extract comments with signal words from a source file."""
    content = _read_file(filepath)
    if not content:
        return []

    signals = []
    for line in content.splitlines():
        line = line.strip()
        for pattern, priority in _COMMENT_SIGNALS:
            m = pattern.search(line)
            if m:
                signal_type = m.group(1).upper()
                text = m.group(2).strip()
                signals.append((f"{signal_type}: {text}", priority))
                break  # One match per line

    return signals


def _split_markdown_sections(content: str) -> List[Tuple[str, str]]:
    """Split markdown content into (heading, body) sections."""
    sections = []
    current_heading = "Introduction"
    current_body: List[str] = []

    for line in content.splitlines():
        if line.startswith("#"):
            if current_body:
                sections.append((current_heading, "\n".join(current_body).strip()))
            current_heading = line.lstrip("#").strip()
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_heading, "\n".join(current_body).strip()))

    return sections


def _guess_module_from_text(text: str, root: str) -> Optional[str]:
    """Try to guess which module a text fragment is about from directory names."""
    text_lower = text.lower()

    # Check if any top-level directory name appears in the text
    try:
        entries = os.listdir(root)
    except OSError:
        return None

    for entry in entries:
        if os.path.isdir(os.path.join(root, entry)) and entry not in SKIP_DIRS:
            if entry.lower() in text_lower:
                return entry

    return None


def _read_file(path: str) -> Optional[str]:
    """Read a file safely."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (IOError, OSError):
        return None
