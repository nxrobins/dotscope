"""Tree-sitter Go analyzer.

Produces the same FileAnalysis shape as the Python stdlib ast analyzer.
Handles struct methods via receiver linking, interface embedding,
and go.mod-aware import resolution.
"""

import os
from typing import Dict, List, Optional

from ._base import BaseAnalyzer
from ._treesitter import (
    parse, node_text, find_child, find_children, walk_type
)
from ...models.core import (
    FileAnalysis, ResolvedImport, ClassInfo, FunctionInfo, ExportedSymbol,
)


class GoAnalyzer(BaseAnalyzer):

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        source_bytes = source.encode("utf-8")
        try:
            root = parse("go", source_bytes)
        except Exception:
            return None

        imports = self._extract_imports(root, source_bytes)
        structs, interfaces = self._extract_types(root, source_bytes)
        functions, methods = self._extract_functions(root, source_bytes)

        # Link methods to structs via receiver type
        struct_map: Dict[str, ClassInfo] = {s.name: s for s in structs}
        for receiver_type, method_name in methods:
            clean_type = receiver_type.lstrip("*")
            if clean_type in struct_map:
                struct_map[clean_type].methods.append(method_name)
                struct_map[clean_type].method_count += 1

        all_classes = structs + interfaces
        exports = self._extract_exports(all_classes, functions)
        docstring = self._extract_package_doc(root, source_bytes)

        return FileAnalysis(
            path=filepath,
            language="go",
            imports=imports,
            classes=all_classes,
            functions=functions,
            exports=exports,
            docstring=docstring,
            node_count=self._count_nodes(root),
        )

    def _extract_imports(self, root, source_bytes) -> List[ResolvedImport]:
        imports = []

        for decl in walk_type(root, "import_declaration"):
            # Single import: import "fmt"
            for spec in walk_type(decl, "import_spec"):
                path_node = find_child(spec, "interpreted_string_literal")
                if not path_node:
                    continue
                raw = _strip_quotes(node_text(path_node, source_bytes))

                # Alias
                name_node = find_child(spec, "package_identifier") or find_child(spec, "dot")
                alias = node_text(name_node, source_bytes) if name_node else ""
                is_star = alias == "."

                imports.append(ResolvedImport(
                    raw=raw,
                    module=raw.split("/")[-1] if "/" in raw else raw,
                    names=[alias] if alias and alias != "." else [],
                    is_star=is_star,
                    line=spec.start_point[0] + 1,
                ))

        return imports

    def _extract_types(self, root, source_bytes):
        structs = []
        interfaces = []

        for decl in walk_type(root, "type_declaration"):
            for spec in find_children(decl, "type_spec"):
                name_node = find_child(spec, "type_identifier")
                if not name_node:
                    continue
                name = node_text(name_node, source_bytes)
                is_public = name[0].isupper() if name else False

                struct_type = find_child(spec, "struct_type")
                interface_type = find_child(spec, "interface_type")

                if struct_type:
                    structs.append(ClassInfo(
                        name=name,
                        bases=[],
                        methods=[],
                        method_count=0,
                        is_public=is_public,
                        line=spec.start_point[0] + 1,
                    ))
                elif interface_type:
                    # Embedded interfaces act like base classes
                    bases = []
                    for child in interface_type.children:
                        if child.type == "type_elem":
                            # Embedded type: type_elem > type_identifier
                            tid = find_child(child, "type_identifier")
                            if tid:
                                bases.append(node_text(tid, source_bytes))
                            # Qualified: type_elem > qualified_type
                            qt = find_child(child, "qualified_type")
                            if qt:
                                bases.append(node_text(qt, source_bytes))

                    # Interface methods (method_elem nodes)
                    methods = []
                    for method_elem in walk_type(interface_type, "method_elem"):
                        method_name = find_child(method_elem, "field_identifier")
                        if method_name:
                            methods.append(node_text(method_name, source_bytes))

                    interfaces.append(ClassInfo(
                        name=name,
                        bases=bases,
                        methods=methods,
                        method_count=len(methods),
                        is_public=is_public,
                        line=spec.start_point[0] + 1,
                    ))

        return structs, interfaces

    def _extract_functions(self, root, source_bytes):
        """Extract functions and methods. Returns (functions, methods).

        methods is a list of (receiver_type, method_name) for linking to structs.
        """
        functions = []
        methods_to_link = []

        # Regular functions
        for node in walk_type(root, "function_declaration"):
            name_node = find_child(node, "identifier")
            if not name_node:
                continue
            name = node_text(name_node, source_bytes)
            params = self._extract_params(node, source_bytes)
            return_type = self._extract_return_type(node, source_bytes)

            functions.append(FunctionInfo(
                name=name,
                params=params,
                arg_count=len(params),
                return_type=return_type,
                is_public=name[0].isupper() if name else False,
                line=node.start_point[0] + 1,
            ))

        # Methods (with receiver)
        for node in walk_type(root, "method_declaration"):
            name_node = find_child(node, "field_identifier")
            if not name_node:
                continue
            name = node_text(name_node, source_bytes)
            params = self._extract_params(node, source_bytes)
            return_type = self._extract_return_type(node, source_bytes)

            # Extract receiver type
            receiver = find_child(node, "parameter_list")
            receiver_type = ""
            if receiver:
                for param in receiver.children:
                    if param.type == "parameter_declaration":
                        type_node = (
                            find_child(param, "pointer_type") or
                            find_child(param, "type_identifier")
                        )
                        if type_node:
                            receiver_type = node_text(type_node, source_bytes)

            functions.append(FunctionInfo(
                name=name,
                params=params,
                arg_count=len(params),
                return_type=return_type,
                is_public=name[0].isupper() if name else False,
                line=node.start_point[0] + 1,
            ))

            if receiver_type:
                methods_to_link.append((receiver_type, name))

        return functions, methods_to_link

    def _extract_params(self, node, source_bytes) -> List[str]:
        """Extract parameter names from a function's parameter_list."""
        params = []
        # Skip the first parameter_list (receiver) for methods
        param_lists = find_children(node, "parameter_list")
        if not param_lists:
            return params

        # For methods, the second parameter_list is the actual params
        # For functions, the first is the params
        target = param_lists[-1] if len(param_lists) > 1 else param_lists[0]
        # But for function_declaration, there's only one
        if node.type == "function_declaration":
            target = param_lists[0]

        for param in find_children(target, "parameter_declaration"):
            for id_node in find_children(param, "identifier"):
                params.append(node_text(id_node, source_bytes))

        return params

    def _extract_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract Go return type (result)."""
        for child in node.children:
            if child.type in ("type_identifier", "pointer_type",
                              "parameter_list", "qualified_type"):
                # Check if this is after the params (is the result)
                param_lists = find_children(node, "parameter_list")
                if child.type == "parameter_list" and child in param_lists:
                    # Named return values
                    if param_lists.index(child) > 0 or node.type == "function_declaration":
                        continue
                if child.start_byte > (param_lists[-1].end_byte if param_lists else 0):
                    return node_text(child, source_bytes)
        return None

    def _extract_exports(self, classes, functions) -> List[ExportedSymbol]:
        """In Go, exported = capitalized name."""
        exports = []
        for cls in classes:
            if cls.is_public:
                exports.append(ExportedSymbol(name=cls.name, kind="class"))
        for fn in functions:
            if fn.is_public:
                exports.append(ExportedSymbol(name=fn.name, kind="function"))
        return exports

    def _extract_package_doc(self, root, source_bytes) -> Optional[str]:
        """Extract package-level GoDoc comment."""
        for child in root.children:
            if child.type == "comment":
                text = node_text(child, source_bytes)
                if text.startswith("//"):
                    return text.lstrip("/ ").strip()
            elif child.type == "package_clause":
                # Check comment before package clause
                if child.prev_named_sibling and child.prev_named_sibling.type == "comment":
                    text = node_text(child.prev_named_sibling, source_bytes)
                    return text.lstrip("/ ").strip()
                break
            else:
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
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def resolve_go_import(
    imp: ResolvedImport,
    source_file: str,
    root: str,
) -> Optional[str]:
    """Resolve a Go import to a file path relative to root.

    Reads go.mod to determine the module path. If the import starts
    with the module path, maps it to the local directory.
    """
    module_path = _read_go_mod(root)
    if not module_path:
        return None

    import_path = imp.raw
    if not import_path.startswith(module_path):
        return None  # External package

    # Strip module prefix to get relative path
    rel = import_path[len(module_path):].lstrip("/")
    candidate = os.path.join(root, rel)

    if os.path.isdir(candidate):
        # Find a .go file in the directory
        for f in sorted(os.listdir(candidate)):
            if f.endswith(".go") and not f.endswith("_test.go"):
                return os.path.join(rel, f)

    return None


_go_mod_cache: Dict[str, Optional[str]] = {}


def _read_go_mod(root: str) -> Optional[str]:
    """Read module path from go.mod."""
    if root in _go_mod_cache:
        return _go_mod_cache[root]

    go_mod = os.path.join(root, "go.mod")
    result = None
    if os.path.exists(go_mod):
        try:
            with open(go_mod, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("module "):
                        result = line.split(None, 1)[1].strip()
                        break
        except (IOError, IndexError):
            pass

    _go_mod_cache[root] = result
    return result
