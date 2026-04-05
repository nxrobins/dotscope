"""Tree-sitter Rust analyzer.

Produces the same FileAnalysis shape as the Python stdlib ast analyzer.
Handles struct/enum/trait definitions, impl blocks, and use statements.
"""

from typing import Dict, List, Optional

from ._base import BaseAnalyzer
from ._treesitter import (
    parse, node_text, find_child, find_children, walk_type
)
from ...models.core import (
    FileAnalysis, ResolvedImport, ClassInfo, FunctionInfo, ExportedSymbol,
)


class RustAnalyzer(BaseAnalyzer):

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        source_bytes = source.encode("utf-8")
        try:
            root = parse("rust", source_bytes)
        except Exception:
            return None

        imports = self._extract_imports(root, source_bytes)
        structs_and_traits = self._extract_types(root, source_bytes)
        functions, methods = self._extract_functions(root, source_bytes)

        # Link methods to structs via impl blocks
        struct_map: Dict[str, ClassInfo] = {s.name: s for s in structs_and_traits}
        for receiver_type, method_name in methods:
            if receiver_type in struct_map:
                struct_map[receiver_type].methods.append(method_name)
                struct_map[receiver_type].method_count += 1

        exports = self._extract_exports(structs_and_traits, functions)
        docstring = self._extract_file_doc(root, source_bytes)

        return FileAnalysis(
            path=filepath,
            language="rust",
            imports=imports,
            classes=structs_and_traits,
            functions=functions,
            exports=exports,
            docstring=docstring,
            node_count=self._count_nodes(root),
        )

    def _extract_imports(self, root, source_bytes) -> List[ResolvedImport]:
        imports = []
        for decl in walk_type(root, "use_declaration"):
            # Tree-sitter rust 'use_declaration' -> child 'scoped_identifier' or 'scoped_use_list' etc.
            # We'll just grab the full text of the import for simplicity in v1
            # as Rust use paths don't map perfectly to 1:1 file paths without cargo
            argument = find_child(decl, "scoped_identifier") or find_child(decl, "identifier")
            if argument:
                raw = node_text(argument, source_bytes)
                imports.append(ResolvedImport(
                    raw=raw,
                    module=raw.split("::")[0],
                    names=[],
                    is_star=False,
                    line=decl.start_point[0] + 1,
                ))
            elif find_child(decl, "use_wildcard"):
                # fallback for basic wildcard
                path = find_child(find_child(decl, "use_wildcard"), "scoped_identifier")
                if path:
                    raw = node_text(path, source_bytes)
                    imports.append(ResolvedImport(
                        raw=raw, module=raw.split("::")[0], names=[], is_star=True, line=decl.start_point[0] + 1
                    ))
        return imports

    def _extract_types(self, root, source_bytes) -> List[ClassInfo]:
        types = []
        
        # Structs
        for node in walk_type(root, "struct_item"):
            name_node = find_child(node, "type_identifier")
            if name_node:
                name = node_text(name_node, source_bytes)
                is_public = bool(find_child(node, "visibility_modifier"))
                types.append(ClassInfo(
                    name=name, bases=[], methods=[], method_count=0,
                    is_public=is_public, line=node.start_point[0] + 1
                ))

        # Enums
        for node in walk_type(root, "enum_item"):
            name_node = find_child(node, "type_identifier")
            if name_node:
                name = node_text(name_node, source_bytes)
                is_public = bool(find_child(node, "visibility_modifier"))
                types.append(ClassInfo(
                    name=name, bases=[], methods=[], method_count=0,
                    is_public=is_public, line=node.start_point[0] + 1
                ))

        # Traits
        for node in walk_type(root, "trait_item"):
            name_node = find_child(node, "type_identifier")
            if name_node:
                name = node_text(name_node, source_bytes)
                is_public = bool(find_child(node, "visibility_modifier"))
                
                # Extract methods from trait body
                methods = []
                body = find_child(node, "declaration_list")
                if body:
                    for f in find_children(body, "function_item") + find_children(body, "function_signature_item"):
                        fname = find_child(f, "identifier")
                        if fname:
                            methods.append(node_text(fname, source_bytes))

                types.append(ClassInfo(
                    name=name, bases=[], methods=methods, method_count=len(methods),
                    is_public=is_public, line=node.start_point[0] + 1
                ))

        return types

    def _extract_functions(self, root, source_bytes):
        functions = []
        methods_to_link = []

        # Standard free functions
        for node in walk_type(root, "function_item"):
            parent = node.parent
            if parent and parent.type in ("declaration_list",): # inside impl or trait
                continue # Handled by impl blocks
                
            name_node = find_child(node, "identifier")
            if not name_node:
                continue
                
            name = node_text(name_node, source_bytes)
            is_public = bool(find_child(node, "visibility_modifier"))
            functions.append(FunctionInfo(
                name=name, params=[], arg_count=0, return_type=None,
                is_public=is_public, line=node.start_point[0] + 1
            ))

        # Impl blocks
        for node in walk_type(root, "impl_item"):
            # Could be `impl Struct` or `impl Trait for Struct`
            # tree-sitter-rust has type_identifier for the struct
            type_id = find_child(node, "type_identifier") or find_child(node, "scoped_type_identifier")
            if not type_id:
                continue
            
            struct_name = node_text(type_id, source_bytes)
            body = find_child(node, "declaration_list")
            if body:
                for f in find_children(body, "function_item"):
                    fname_node = find_child(f, "identifier")
                    if fname_node:
                        fname = node_text(fname_node, source_bytes)
                        is_public = bool(find_child(f, "visibility_modifier"))
                        
                        functions.append(FunctionInfo(
                            name=fname, params=[], arg_count=0, return_type=None,
                            is_public=is_public, line=f.start_point[0] + 1
                        ))
                        methods_to_link.append((struct_name, fname))

        return functions, methods_to_link

    def _extract_exports(self, types, functions) -> List[ExportedSymbol]:
        exports = []
        for cls in types:
            if cls.is_public:
                exports.append(ExportedSymbol(name=cls.name, kind="class"))
        for fn in functions:
            if fn.is_public:
                exports.append(ExportedSymbol(name=fn.name, kind="function"))
        return exports

    def _extract_file_doc(self, root, source_bytes) -> Optional[str]:
        for child in root.children:
            if child.type == "line_comment" or child.type == "block_comment":
                text = node_text(child, source_bytes)
                if text.startswith("//!") or text.startswith("/*!"):
                    return text.strip("/!* \n")
        return None

    def _count_nodes(self, root) -> int:
        count = 0
        stack = [root]
        while stack:
            n = stack.pop()
            count += 1
            stack.extend(n.children)
        return count
