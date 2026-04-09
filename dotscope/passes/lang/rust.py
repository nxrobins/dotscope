import logging
from typing import Optional

from ...models.core import ClassInfo, ExportedSymbol, FileAnalysis, FunctionInfo, ResolvedImport
from ._base import BaseAnalyzer
from ._treesitter import AVAILABLE, find_child, node_text, parse

logger = logging.getLogger(__name__)

def expand_rust_use(text: str) -> list[str]:
    text = "".join(text.split())
    queue = [text]
    results = []
    MAX_EXPANSIONS = 2000
    
    while queue and len(results) + len(queue) < MAX_EXPANSIONS:
        s = queue.pop(0)
        if "{" not in s:
            results.append(s)
            continue
            
        start = s.rfind("{")
        end = s.find("}", start)
        if end == -1:
            results.append(s)
            continue
            
        prefix = s[:start]
        suffix = s[end+1:]
        inner = s[start+1:end]
        
        for p in inner.split(","):
            if not p: continue
            if p == "self" and prefix.endswith("::"):
                queue.append(prefix[:-2] + suffix)
            else:
                queue.append(prefix + p + suffix)
                
    if len(results) + len(queue) >= MAX_EXPANSIONS:
        return [text] # Graceful degradation
        
    return list(set(results))

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
                    
                for path in expand_rust_use(text):
                    is_relative = path.startswith("crate::") or path.startswith("super::") or path.startswith("self::")
                    api.imports.append(ResolvedImport(
                        raw=path,
                        names=[path.split("::")[-1]],
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
