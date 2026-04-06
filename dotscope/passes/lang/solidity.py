"""Tree-sitter Solidity analyzer.

Produces the same FileAnalysis shape as the Python stdlib ast analyzer.
Handles contract/interface/library declarations, inheritance tracking,
function visibility, modifier definitions, and Foundry/Hardhat import
resolution (including remappings.txt).
"""

import os
from typing import Dict, List, Optional, Tuple

from ._base import BaseAnalyzer
from ._treesitter import (
    parse, node_text, find_child, find_children, walk_type
)
from ...models.core import (
    FileAnalysis, ResolvedImport, ClassInfo, FunctionInfo, ExportedSymbol,
)
from ...paths import normalize_relative_path


class SolidityAnalyzer(BaseAnalyzer):

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        source_bytes = source.encode("utf-8")
        try:
            root = parse("solidity", source_bytes)
        except Exception:
            return None

        imports = self._extract_imports(root, source_bytes)
        contracts, interfaces, libraries = self._extract_types(root, source_bytes)
        functions = self._extract_functions(root, source_bytes)
        all_classes = contracts + interfaces + libraries
        exports = self._extract_exports(all_classes, functions)
        docstring = self._extract_file_docstring(root, source_bytes)

        return FileAnalysis(
            path=filepath,
            language="solidity",
            imports=imports,
            classes=all_classes,
            functions=functions,
            exports=exports,
            docstring=docstring,
            node_count=self._count_nodes(root),
        )

    def _extract_imports(self, root, source_bytes) -> List[ResolvedImport]:
        imports = []

        for node in walk_type(root, "import_directive"):
            source_node = find_child(node, "string") or find_child(node, "import_path")
            if source_node is None:
                for child in node.children:
                    if child.type in ("string", "string_literal"):
                        source_node = child
                        break

            if source_node is None:
                continue

            raw = _strip_quotes(node_text(source_node, source_bytes))
            if not raw:
                continue

            is_relative = raw.startswith("./") or raw.startswith("../")

            names = []
            for spec in walk_type(node, "import_declaration"):
                id_node = find_child(spec, "identifier")
                if id_node:
                    names.append(node_text(id_node, source_bytes))

            is_star = False
            for child in node.children:
                if child.type == "identifier":
                    text = node_text(child, source_bytes)
                    if text and text not in names:
                        names.append(text)
                elif child.type == "*":
                    is_star = True

            imports.append(ResolvedImport(
                raw=raw,
                module=_module_from_path(raw),
                names=names,
                is_star=is_star,
                is_relative=is_relative,
                line=node.start_point[0] + 1,
            ))

        return imports

    def _extract_types(self, root, source_bytes):
        contracts = []
        interfaces = []
        libraries = []

        for node in walk_type(root, "contract_declaration"):
            name, bases = self._parse_type_header(node, source_bytes)
            methods = self._extract_type_methods(node, source_bytes)
            contracts.append(ClassInfo(
                name=name,
                bases=bases,
                methods=[m[0] for m in methods],
                method_count=len(methods),
                is_public=True,
                line=node.start_point[0] + 1,
            ))

        for node in walk_type(root, "interface_declaration"):
            name, bases = self._parse_type_header(node, source_bytes)
            methods = self._extract_type_methods(node, source_bytes)
            interfaces.append(ClassInfo(
                name=name,
                bases=bases,
                methods=[m[0] for m in methods],
                method_count=len(methods),
                is_abstract=True,
                is_public=True,
                line=node.start_point[0] + 1,
            ))

        for node in walk_type(root, "library_declaration"):
            name_node = find_child(node, "identifier")
            name = node_text(name_node, source_bytes) if name_node else ""
            methods = self._extract_type_methods(node, source_bytes)
            libraries.append(ClassInfo(
                name=name,
                bases=[],
                methods=[m[0] for m in methods],
                method_count=len(methods),
                is_public=True,
                line=node.start_point[0] + 1,
            ))

        return contracts, interfaces, libraries

    def _parse_type_header(self, node, source_bytes) -> Tuple[str, List[str]]:
        """Extract name and inheritance list from a contract/interface declaration."""
        name_node = find_child(node, "identifier")
        name = node_text(name_node, source_bytes) if name_node else ""

        bases = []
        for spec in walk_type(node, "inheritance_specifier"):
            type_node = (
                find_child(spec, "user_defined_type")
                or find_child(spec, "identifier")
            )
            if type_node:
                bases.append(node_text(type_node, source_bytes))

        return name, bases

    def _extract_type_methods(self, node, source_bytes) -> List[Tuple[str, bool]]:
        """Extract (method_name, is_public) pairs from a contract/interface/library body."""
        methods = []
        body = find_child(node, "contract_body")
        if body is None:
            return methods

        for fn in walk_type(body, "function_definition"):
            fn_name_node = find_child(fn, "identifier")
            if not fn_name_node:
                continue
            fn_name = node_text(fn_name_node, source_bytes)
            is_pub = self._is_public_function(fn, source_bytes)
            methods.append((fn_name, is_pub))

        return methods

    def _extract_functions(self, root, source_bytes) -> List[FunctionInfo]:
        """Extract all functions, including free functions and modifiers."""
        functions = []

        for node in walk_type(root, "function_definition"):
            name_node = find_child(node, "identifier")
            if not name_node:
                continue
            name = node_text(name_node, source_bytes)
            params = self._extract_params(node, source_bytes)
            is_pub = self._is_public_function(node, source_bytes)
            modifiers = self._extract_modifier_invocations(node, source_bytes)
            return_type = self._extract_return_type(node, source_bytes)

            functions.append(FunctionInfo(
                name=name,
                params=params,
                arg_count=len(params),
                return_type=return_type,
                decorators=modifiers,
                is_public=is_pub,
                line=node.start_point[0] + 1,
            ))

        for node in walk_type(root, "modifier_definition"):
            name_node = find_child(node, "identifier")
            if not name_node:
                continue
            name = node_text(name_node, source_bytes)
            params = self._extract_params(node, source_bytes)

            functions.append(FunctionInfo(
                name=name,
                params=params,
                arg_count=len(params),
                decorators=["modifier"],
                is_public=True,
                line=node.start_point[0] + 1,
            ))

        return functions

    def _extract_params(self, node, source_bytes) -> List[str]:
        params = []
        param_list = find_child(node, "parameter_list")
        if not param_list:
            return params

        for param in walk_type(param_list, "parameter"):
            id_node = find_child(param, "identifier")
            if id_node:
                params.append(node_text(id_node, source_bytes))
            else:
                type_node = (
                    find_child(param, "type_name")
                    or find_child(param, "user_defined_type")
                    or find_child(param, "elementary_type")
                )
                if type_node:
                    params.append(node_text(type_node, source_bytes))

        return params

    def _extract_return_type(self, node, source_bytes) -> Optional[str]:
        for child in node.children:
            if child.type == "return_type_definition":
                return node_text(child, source_bytes).strip()
        return None

    def _is_public_function(self, node, source_bytes) -> bool:
        for child in node.children:
            text = node_text(child, source_bytes)
            if text in ("public", "external"):
                return True
            if text in ("private", "internal"):
                return False
        return False

    def _extract_modifier_invocations(self, node, source_bytes) -> List[str]:
        modifiers = []
        for child in walk_type(node, "modifier_invocation"):
            id_node = find_child(child, "identifier")
            if id_node:
                modifiers.append(node_text(id_node, source_bytes))
        return modifiers

    def _extract_exports(self, classes, functions) -> List[ExportedSymbol]:
        exports = []
        for cls in classes:
            exports.append(ExportedSymbol(name=cls.name, kind="class"))
        for fn in functions:
            if fn.is_public:
                exports.append(ExportedSymbol(name=fn.name, kind="function"))
        return exports

    def _extract_file_docstring(self, root, source_bytes) -> Optional[str]:
        if root.child_count == 0:
            return None
        for child in root.children:
            if child.type == "comment":
                text = node_text(child, source_bytes)
                if text.startswith("///") or text.startswith("/**"):
                    return text.strip("/* /\n").strip()
            elif child.type not in ("pragma_directive", "source_file"):
                break
        return None

    def _count_nodes(self, root) -> int:
        count = 0
        stack = [root]
        while stack:
            n = stack.pop()
            count += 1
            stack.extend(n.children)
        return count


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] in ('"', "'"):
        return s[1:-1]
    return s


def _module_from_path(raw: str) -> str:
    """Extract module name from an import path."""
    basename = raw.rsplit("/", 1)[-1] if "/" in raw else raw
    if basename.endswith(".sol"):
        basename = basename[:-4]
    return basename


_remappings_cache: Dict[str, Optional[List[Tuple[str, str]]]] = {}


def resolve_solidity_import(
    imp: ResolvedImport,
    source_file: str,
    root: str,
) -> Optional[str]:
    """Resolve a Solidity import to a file path relative to root.

    Resolution order:
    1. Explicit relative (./  ../): resolve against source file directory
    2. Bare path (no prefix): try local resolution first, then remappings
    3. Remappings.txt (Foundry): apply prefix mappings
    4. External (@openzeppelin, forge-std, etc.): return None
    """
    raw = imp.raw
    source_dir = os.path.dirname(source_file)

    if raw.startswith("./") or raw.startswith("../"):
        candidate = os.path.normpath(os.path.join(source_dir, raw))
        if os.path.isfile(candidate):
            return normalize_relative_path(os.path.relpath(candidate, root))
        return None

    local_candidate = os.path.normpath(os.path.join(source_dir, raw))
    if os.path.isfile(local_candidate):
        return normalize_relative_path(os.path.relpath(local_candidate, root))

    remappings = _load_remappings(root)
    if remappings:
        for prefix, target in remappings:
            if raw.startswith(prefix):
                remapped = raw.replace(prefix, target, 1)
                candidate = os.path.normpath(os.path.join(root, remapped))
                if os.path.isfile(candidate):
                    return normalize_relative_path(os.path.relpath(candidate, root))

    root_candidate = os.path.normpath(os.path.join(root, raw))
    if os.path.isfile(root_candidate):
        return normalize_relative_path(os.path.relpath(root_candidate, root))

    return None


def _load_remappings(root: str) -> Optional[List[Tuple[str, str]]]:
    """Load Foundry-style remappings.txt."""
    if root in _remappings_cache:
        return _remappings_cache[root]

    remappings_file = os.path.join(root, "remappings.txt")
    result = None

    if os.path.isfile(remappings_file):
        try:
            mappings = []
            with open(remappings_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        prefix, target = line.split("=", 1)
                        mappings.append((prefix.strip(), target.strip()))
            if mappings:
                mappings.sort(key=lambda x: len(x[0]), reverse=True)
                result = mappings
        except (IOError, OSError):
            pass

    _remappings_cache[root] = result
    return result
