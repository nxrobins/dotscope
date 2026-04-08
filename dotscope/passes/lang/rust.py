import logging
from typing import Optional

from ...models.core import ClassInfo, ExportedSymbol, FileAnalysis, FunctionInfo, ResolvedImport
from ._base import BaseAnalyzer
from ._treesitter import AVAILABLE, find_child, node_text, parse

logger = logging.getLogger(__name__)

class RustAnalyzer(BaseAnalyzer):
    """Parses Rust files strictly using tree-sitter.
    
    Zero regex fallback policy. Captures structs, traits, impl blocks, and functions.
    Crucially identifies explicit `mod` declarations to map the physical dependency graph
    alongside relative `use` statements.
    """

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        if not AVAILABLE:
            return None

        try:
            source_bytes = source.encode("utf-8", errors="replace")
            root = parse("rust", source_bytes)
        except Exception as e:
            logger.debug(f"Failed to tree-sitter parse Rust {filepath}: {e}")
            return None

        api = FileAnalysis(path=filepath, language="rust")

        for node in root.children:
            if node.type == "mod_item":
                # mod name;
                name_node = find_child(node, "identifier")
                if name_node:
                    raw = node_text(name_node, source_bytes)
                    # We preface mod links specially so ast_analyzer handles them differently.
                    api.imports.append(ResolvedImport(
                        raw=f"mod:{raw}",
                        module=raw,
                        names=[],
                        is_relative=True
                    ))
            elif node.type == "use_declaration":
                # use std::collections::HashMap;
                # Note: Extracting full path simply by parsing text of the use clause, minus "use" and ";"
                text = node_text(node, source_bytes)
                text = text.replace("use ", "").replace(";", "").strip()
                if text.startswith("pub "):
                    text = text.replace("pub ", "", 1).strip()
                    
                is_relative = text.startswith("crate::") or text.startswith("super::") or text.startswith("self::")
                
                api.imports.append(ResolvedImport(
                    raw=text,
                    names=[text.split("::")[-1].strip("{} ")],
                    is_relative=is_relative
                ))
            elif node.type in ("struct_item", "trait_item", "enum_item"):
                name_node = find_child(node, "type_identifier")
                if name_node:
                    name = node_text(name_node, source_bytes)
                    is_public = False
                    # Check for 'pub' modifier
                    if node.children and node.children[0].type.startswith("visibility_modifier"):
                        is_public = True

                    api.classes.append(ClassInfo(
                        name=name,
                        is_public=is_public,
                        line=node.start_point[0] + 1
                    ))
                    if is_public:
                        api.exports.append(ExportedSymbol(name=name, kind="class", is_public=True))
                        
            elif node.type == "function_item":
                name_node = find_child(node, "identifier")
                if name_node:
                    name = node_text(name_node, source_bytes)
                    is_public = False
                    if node.children and node.children[0].type.startswith("visibility_modifier"):
                        is_public = True
                    api.functions.append(FunctionInfo(
                        name=name,
                        is_public=is_public,
                        line=node.start_point[0] + 1
                    ))
                    if is_public:
                        api.exports.append(ExportedSymbol(name=name, kind="function", is_public=True))

            elif node.type == "impl_item":
                # impl_item -> type_identifier
                type_node = find_child(node, "type_identifier")
                if type_node:
                    name = node_text(type_node, source_bytes)
                    # We can associate functions inside the impl block
                    body = find_child(node, "declaration_list")
                    if body:
                        for child in body.children:
                            if child.type == "function_item":
                                fn_name_node = find_child(child, "identifier")
                                if fn_name_node:
                                    fn_name = node_text(fn_name_node, source_bytes)
                                    is_public = False
                                    if child.children and child.children[0].type.startswith("visibility_modifier"):
                                        is_public = True
                                    # Since they are impl, they export if public
                                    if is_public:
                                        api.exports.append(ExportedSymbol(name=f"{name}::{fn_name}", kind="function", is_public=True))
        return api
