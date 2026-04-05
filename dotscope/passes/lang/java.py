"""Tree-sitter Java analyzer.

Produces the same FileAnalysis shape as the Python stdlib ast analyzer.
Handles standard Java file structure, nested classes, and implements smart
import resolution for Java source roots (e.g. src/main/java).
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
from ...paths import normalize_relative_path

class JavaAnalyzer(BaseAnalyzer):

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        source_bytes = source.encode("utf-8")
        try:
            root = parse("java", source_bytes)
        except Exception:
            return None

        imports = self._extract_imports(root, source_bytes)
        classes_and_interfaces = self._extract_types(root, source_bytes)
        functions, methods = self._extract_functions(root, source_bytes)

        # Link methods to classes via containment (methods parsed inside the class bodies)
        class_map: Dict[str, ClassInfo] = {c.name: c for c in classes_and_interfaces}
        for parent_class, method_name in methods:
            if parent_class in class_map:
                class_map[parent_class].methods.append(method_name)
                class_map[parent_class].method_count += 1

        exports = self._extract_exports(classes_and_interfaces, functions)
        docstring = self._extract_file_doc(root, source_bytes)

        return FileAnalysis(
            path=filepath,
            language="java",
            imports=imports,
            classes=classes_and_interfaces,
            functions=functions,
            exports=exports,
            docstring=docstring,
            node_count=self._count_nodes(root),
        )

    def _extract_imports(self, root, source_bytes) -> List[ResolvedImport]:
        imports = []
        for node in walk_type(root, "import_declaration"):
            # The scoped identifier or asterisk
            is_star = bool(find_child(node, "asterisk"))
            path_node = find_child(node, "scoped_identifier") or find_child(node, "identifier")
            
            if path_node:
                raw = node_text(path_node, source_bytes)
                imports.append(ResolvedImport(
                    raw=raw,
                    module=raw.split(".")[-1] if "." in raw else raw,
                    names=[],
                    is_star=is_star,
                    line=node.start_point[0] + 1,
                ))
        return imports

    def _extract_types(self, root, source_bytes) -> List[ClassInfo]:
        types = []
        
        # class_declaration, interface_declaration, record_declaration, enum_declaration
        for node_type in ("class_declaration", "interface_declaration", "record_declaration", "enum_declaration"):
            for node in walk_type(root, node_type):
                name_node = find_child(node, "identifier")
                if not name_node:
                    continue
                name = node_text(name_node, source_bytes)
                
                modifiers = find_child(node, "modifiers")
                is_public = False
                if modifiers:
                    for mod in modifiers.children:
                        if node_text(mod, source_bytes) == "public":
                            is_public = True
                            break

                bases = []
                super_interfaces = find_child(node, "super_interfaces")
                if super_interfaces:
                    for type_list in find_children(super_interfaces, "type_list"):
                        for t in find_children(type_list, "type_identifier"):
                            bases.append(node_text(t, source_bytes))
                
                superclass = find_child(node, "superclass")
                if superclass:
                    t = find_child(superclass, "type_identifier")
                    if t:
                        bases.append(node_text(t, source_bytes))

                types.append(ClassInfo(
                    name=name, bases=bases, methods=[], method_count=0,
                    is_public=is_public, line=node.start_point[0] + 1
                ))

        return types


    def _extract_functions(self, root, source_bytes):
        functions = []
        methods_to_link = []

        # Find classes, then find methods inside them
        for cls_node in walk_type(root, "class_declaration") + walk_type(root, "interface_declaration"):
            cls_name_node = find_child(cls_node, "identifier")
            if not cls_name_node: continue
            cls_name = node_text(cls_name_node, source_bytes)
            
            body = find_child(cls_node, "class_body") or find_child(cls_node, "interface_body")
            if not body: continue
            
            for m_node in walk_type(body, "method_declaration"):
                m_name_node = find_child(m_node, "identifier")
                if not m_name_node: continue
                m_name = node_text(m_name_node, source_bytes)
                
                modifiers = find_child(m_node, "modifiers")
                is_public = False
                if modifiers:
                    for mod in modifiers.children:
                        if node_text(mod, source_bytes) in ("public", "protected"):
                            is_public = True
                            
                functions.append(FunctionInfo(
                    name=m_name, params=[], arg_count=0, return_type=None,
                    is_public=is_public, line=m_node.start_point[0] + 1
                ))
                methods_to_link.append((cls_name, m_name))
        
        return functions, methods_to_link

    def _extract_exports(self, types, functions) -> List[ExportedSymbol]:
        exports = []
        for cls in types:
            if cls.is_public:
                exports.append(ExportedSymbol(name=cls.name, kind="class"))
        # we don't usually export individual functions in Java, they belong to classes
        return exports

    def _extract_file_doc(self, root, source_bytes) -> Optional[str]:
        for child in root.children:
            if child.type == "block_comment":
                text = node_text(child, source_bytes)
                if text.startswith("/**"):
                    return text.strip("/* \n")
        return None

    def _count_nodes(self, root) -> int:
        count = 0
        stack = [root]
        while stack:
            n = stack.pop()
            count += 1
            stack.extend(n.children)
        return count


# Java specific source roots
JAVA_SOURCE_ROOTS = [
    os.path.join("src", "main", "java"),
    os.path.join("src", "test", "java"),
    "src",
    os.path.join("app", "src", "main", "java"),
]

def resolve_java_import(
    imp: ResolvedImport,
    source_file: str,
    root: str,
) -> Optional[str]:
    """Smart import resolution for Java.
    
    Java imports heavily rely on nested directories (e.g. com.enterprise.module).
    This function searches through standard Java root prefixes to find a matching file.
    """
    if not imp.raw:
        return None
        
    # Convert com.enterprise.Foo to com/enterprise/Foo
    relative_path_base = imp.raw.replace(".", os.sep)
    
    candidates = []
    
    # Try appending generic .java to the path
    # For wildcard imports (com.enterprise.*), we'd just want com/enterprise.
    if imp.is_star:
        # If it's a directory export, return the directory path.
        pass
    else:
        relative_path_base += ".java"
        
    for prefix in JAVA_SOURCE_ROOTS:
        full_candidate = os.path.join(root, prefix, relative_path_base)
        if os.path.exists(full_candidate):
            # Normalise the relative path from the absolute repo root
            return normalize_relative_path(os.path.relpath(full_candidate, root))
        
    # Fallback to direct absolute without prefix, just in case
    full_direct = os.path.join(root, relative_path_base)
    if os.path.exists(full_direct):
        return normalize_relative_path(os.path.relpath(full_direct, root))
        
    return None
