"""AST-powered code analysis. Structural understanding of source files.

Python: uses stdlib `ast` module — zero dependencies.
JS/TS: enhanced regex (no heavy AST dep for v1).
Go: enhanced regex.
"""

import ast
import os
import re
from typing import Optional

from ..models import (
    ClassInfo,
    ExportedSymbol,
    FileAnalysis,
    FunctionInfo,
    ResolvedImport,
)

# Cache: (path, mtime) → FileAnalysis
_analysis_cache: dict[tuple[str, float], FileAnalysis] = {}


def analyze_file(filepath: str, language: str) -> Optional[FileAnalysis]:
    """Analyze a source file and extract its full structural API.

    Results are cached by (path, mtime) to avoid re-parsing unchanged files.
    """
    try:
        mtime = os.path.getmtime(filepath)
        cache_key = (filepath, mtime)
        if cache_key in _analysis_cache:
            return _analysis_cache[cache_key]
    except OSError:
        pass

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except (IOError, OSError):
        return None

    result = None
    if language == "python":
        result = _analyze_python(filepath, source)
    else:
        # tree-sitter for JS/TS/Go, regex fallback
        from .lang import get_analyzer
        ts_analyzer = get_analyzer(language)
        if ts_analyzer:
            result = ts_analyzer(filepath, source)
        if result is None:
            if language in ("javascript", "typescript"):
                result = _analyze_js(filepath, source)
            elif language == "go":
                result = _analyze_go(filepath, source)

    if result:
        try:
            _analysis_cache[(filepath, os.path.getmtime(filepath))] = result
        except OSError:
            pass

    return result


# ---------------------------------------------------------------------------
# Python AST analysis
# ---------------------------------------------------------------------------

def _analyze_python(filepath: str, source: str) -> Optional[FileAnalysis]:
    """Full AST walk of a Python file."""
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return None

    api = FileAnalysis(
        path=filepath,
        language="python",
        is_init=os.path.basename(filepath) == "__init__.py",
        node_count=len(list(ast.walk(tree))),
    )

    # Module docstring
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        api.docstring = tree.body[0].value.value

    # Detect TYPE_CHECKING blocks
    type_checking_lines = _find_type_checking_lines(tree)
    all_decorators = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                api.imports.append(ResolvedImport(
                    raw=alias.name,
                    module=top_module,
                    names=[alias.asname or alias.name],
                    is_relative=False,
                    is_conditional=_is_conditional(node, tree),
                    is_type_only=getattr(node, "lineno", 0) in type_checking_lines,
                    line=getattr(node, "lineno", 0),
                ))
        elif isinstance(node, ast.ImportFrom):
            mod_str = node.module or ""
            top_module = mod_str.split(".")[0] if mod_str else ""
            is_star = any(a.name == "*" for a in node.names)
            names = [a.name for a in node.names]
            api.imports.append(ResolvedImport(
                raw=f"{'.' * node.level}{mod_str}",
                module=top_module,
                names=names,
                is_relative=node.level > 0,
                is_star=is_star,
                is_conditional=_is_conditional(node, tree),
                is_type_only=getattr(node, "lineno", 0) in type_checking_lines,
                line=getattr(node, "lineno", 0),
            ))

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls = _extract_class(node)
            api.classes.append(cls)
            all_decorators.update(cls.decorators)
            api.exports.append(ExportedSymbol(
                name=node.name, kind="class",
                is_public=not node.name.startswith("_"),
            ))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = _extract_function(node)
            api.functions.append(fn)
            all_decorators.update(fn.decorators)
            api.exports.append(ExportedSymbol(
                name=node.name, kind="function",
                is_public=not node.name.startswith("_"),
            ))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                        api.all_list = [
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
                    if target.id.isupper() or not target.id.startswith("_"):
                        api.exports.append(ExportedSymbol(
                            name=target.id,
                            kind="constant" if target.id.isupper() else "variable",
                            is_public=not target.id.startswith("_"),
                        ))

        elif isinstance(node, ast.If):
            if _is_main_guard(node):
                api.is_entry_point = True

    api.decorators_used = sorted(all_decorators)

    # Detect re-exports: names in __all__ that are also imported
    if api.all_list:
        imported_names = set()
        for imp in api.imports:
            imported_names.update(imp.names)
        api.reexports = [n for n in api.all_list if n in imported_names]

    return api


def _extract_class(node: ast.ClassDef) -> ClassInfo:
    """Extract class definition details."""
    bases = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(ast.unparse(base))

    methods = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(item.name)

    decorators = [_decorator_name(d) for d in node.decorator_list]
    is_abstract = any("abstract" in d.lower() for d in decorators) or any(
        "ABC" in b for b in bases
    )

    return ClassInfo(
        name=node.name,
        bases=bases,
        methods=methods,
        method_count=len(methods),
        decorators=decorators,
        is_abstract=is_abstract,
        is_public=not node.name.startswith("_"),
        line=getattr(node, "lineno", 0),
    )


def _extract_function(node) -> FunctionInfo:
    """Extract function definition details."""
    params = []
    for arg in node.args.args:
        param = arg.arg
        if arg.annotation:
            try:
                param += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        params.append(param)

    return_type = None
    if node.returns:
        try:
            return_type = ast.unparse(node.returns)
        except Exception:
            pass

    decorators = [_decorator_name(d) for d in node.decorator_list]

    return FunctionInfo(
        name=node.name,
        params=params,
        arg_count=len(node.args.args),
        return_type=return_type,
        decorators=decorators,
        is_public=not node.name.startswith("_"),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        complexity=_compute_complexity(node),
        line=getattr(node, "lineno", 0),
    )


def _decorator_name(node) -> str:
    """Extract decorator name as string."""
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{ast.unparse(node)}"
        return "unknown"


def _find_type_checking_lines(tree) -> set:
    """Find line numbers inside TYPE_CHECKING blocks."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            is_tc = False
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                is_tc = True
            elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                is_tc = True
            if is_tc:
                for child in ast.walk(node):
                    if hasattr(child, "lineno"):
                        lines.add(child.lineno)
    return lines


def _compute_complexity(node) -> int:
    """Count branching nodes in a function body as complexity proxy."""
    count = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.Try,
                               ast.ExceptHandler, ast.With, ast.Assert)):
            count += 1
    return count


def _is_conditional(node, tree) -> bool:
    """Check if an import is inside a try/except or if block."""
    for parent in ast.walk(tree):
        for attr in ("body", "handlers", "orelse", "finalbody"):
            children = getattr(parent, attr, None)
            if isinstance(children, list) and node in children:
                if isinstance(parent, (ast.Try, ast.If, ast.ExceptHandler)):
                    return True
    return False


def _is_main_guard(node: ast.If) -> bool:
    """Check if this is `if __name__ == '__main__'`."""
    test = node.test
    if isinstance(test, ast.Compare):
        if (
            isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.comparators) == 1
        ):
            comp = test.comparators[0]
            if isinstance(comp, ast.Constant) and comp.value == "__main__":
                return True
    return False


# ---------------------------------------------------------------------------
# JS/TS analysis (enhanced regex)
# ---------------------------------------------------------------------------

def _analyze_js(filepath: str, source: str) -> Optional[FileAnalysis]:
    """Enhanced regex-based JS/TS analysis."""
    api = FileAnalysis(path=filepath, language="javascript")

    for line in source.splitlines():
        stripped = line.strip()

        # import X from '...'
        m = re.match(r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]""", stripped)
        if m:
            api.imports.append(ResolvedImport(
                raw=m.group(2), names=[m.group(1)],
                is_relative=m.group(2).startswith("."),
            ))
            continue

        # import { X, Y } from '...'
        m = re.match(r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""", stripped)
        if m:
            names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")]
            api.imports.append(ResolvedImport(
                raw=m.group(2), names=names,
                is_relative=m.group(2).startswith("."),
            ))
            continue

        # import * as X from '...'
        m = re.match(r"""import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]""", stripped)
        if m:
            api.imports.append(ResolvedImport(
                raw=m.group(2), names=[m.group(1)],
                is_relative=m.group(2).startswith("."), is_star=True,
            ))
            continue

        # require('...')
        m = re.search(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", stripped)
        if m:
            api.imports.append(ResolvedImport(
                raw=m.group(1), names=[],
                is_relative=m.group(1).startswith("."),
            ))
            continue

        # Dynamic import('...')
        m = re.search(r"""import\(\s*['"]([^'"]+)['"]\s*\)""", stripped)
        if m:
            api.imports.append(ResolvedImport(
                raw=m.group(1), names=[],
                is_relative=m.group(1).startswith("."),
                is_conditional=True,  # dynamic = conditional
            ))

        # export default function/class X
        m = re.match(r"export\s+default\s+(function|class)\s+(\w+)", stripped)
        if m:
            kind = m.group(1)
            api.exports.append(ExportedSymbol(name=m.group(2), kind=kind, is_public=True))
            if kind == "class":
                api.classes.append(ClassInfo(name=m.group(2), is_public=True))
            else:
                api.functions.append(FunctionInfo(name=m.group(2), is_public=True))
            continue

        # export function/class X
        m = re.match(r"export\s+(function|class)\s+(\w+)", stripped)
        if m:
            kind = m.group(1)
            api.exports.append(ExportedSymbol(name=m.group(2), kind=kind, is_public=True))
            if kind == "class":
                api.classes.append(ClassInfo(name=m.group(2), is_public=True))
            else:
                api.functions.append(FunctionInfo(name=m.group(2), is_public=True))
            continue

        # export const/let/var X
        m = re.match(r"export\s+(?:const|let|var)\s+(\w+)", stripped)
        if m:
            api.exports.append(ExportedSymbol(name=m.group(1), kind="variable", is_public=True))

    return api


# ---------------------------------------------------------------------------
# Go analysis (enhanced regex)
# ---------------------------------------------------------------------------

def _analyze_go(filepath: str, source: str) -> Optional[FileAnalysis]:
    """Enhanced regex-based Go analysis."""
    api = FileAnalysis(path=filepath, language="go")

    in_import_block = False
    for line in source.splitlines():
        stripped = line.strip()

        # Imports
        if stripped == "import (":
            in_import_block = True
            continue
        if in_import_block and stripped == ")":
            in_import_block = False
            continue
        if in_import_block:
            m = re.match(r'(?:\w+\s+)?"([^"]+)"', stripped)
            if m:
                api.imports.append(ResolvedImport(raw=m.group(1), names=[]))
            continue
        m = re.match(r'import\s+"([^"]+)"', stripped)
        if m:
            api.imports.append(ResolvedImport(raw=m.group(1), names=[]))
            continue

        # Exported functions (capitalized)
        m = re.match(r"func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(", stripped)
        if m:
            name = m.group(1)
            is_public = name[0].isupper()
            api.functions.append(FunctionInfo(name=name, is_public=is_public))
            if is_public:
                api.exports.append(ExportedSymbol(name=name, kind="function", is_public=True))

        # Exported types
        m = re.match(r"type\s+(\w+)\s+(struct|interface)", stripped)
        if m:
            name = m.group(1)
            is_public = name[0].isupper()
            api.classes.append(ClassInfo(name=name, is_public=is_public))
            if is_public:
                api.exports.append(ExportedSymbol(name=name, kind="class", is_public=True))

    return api


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------

def resolve_python_import(imp: ResolvedImport, source_file: str, root: str) -> Optional[str]:
    """Resolve a Python import to a file path relative to root."""
    if imp.is_relative:
        source_dir = os.path.dirname(source_file)
        # Count dots: from .. = current dir, from .. = parent, etc.
        dots = 0
        raw = imp.raw
        while raw.startswith("."):
            dots += 1
            raw = raw[1:]

        base = source_dir
        for _ in range(dots - 1):
            base = os.path.dirname(base)

        if raw:
            parts = raw.split(".")
            candidate_base = os.path.join(base, *parts)
        else:
            candidate_base = base

        return _find_python_module(candidate_base, root)

    # Absolute import
    parts = imp.raw.split(".")
    candidate_base = os.path.join(root, *parts)
    return _find_python_module(candidate_base, root)


def _find_python_module(candidate_base: str, root: str) -> Optional[str]:
    """Try to resolve a Python module path to an actual file."""
    candidates = [
        candidate_base + ".py",
        os.path.join(candidate_base, "__init__.py"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.relpath(c, root)
    return None


def resolve_js_import(imp: ResolvedImport, source_file: str, root: str) -> Optional[str]:
    """Resolve a JS/TS import to a file path relative to root."""
    if not imp.raw.startswith("."):
        return None  # Bare module (npm package)

    source_dir = os.path.dirname(source_file)
    base = os.path.normpath(os.path.join(source_dir, imp.raw))
    rel_base = os.path.relpath(base, root)

    exts = [".ts", ".tsx", ".js", ".jsx"]
    for ext in exts:
        if os.path.isfile(os.path.join(root, rel_base + ext)):
            return rel_base + ext
    for idx in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
        candidate = os.path.join(rel_base, idx)
        if os.path.isfile(os.path.join(root, candidate)):
            return candidate
    return None
