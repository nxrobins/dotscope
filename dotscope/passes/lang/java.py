import logging
from typing import Optional

from ...models.core import ClassInfo, ExportedSymbol, FileAnalysis, FunctionInfo, ResolvedImport
from ._base import BaseAnalyzer
from ._treesitter import AVAILABLE, find_child, find_children, node_text, parse, walk_type

logger = logging.getLogger(__name__)

class JavaAnalyzer(BaseAnalyzer):
    """Parses Java files strictly using tree-sitter.
    
    Zero regex fallback policy. Captures classes, methods, and aggressively extracts 
    annotations (like @Inject, @Autowired) since they functionally define the DI architecture.
    """

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        if not AVAILABLE:
            return None

        try:
            source_bytes = source.encode("utf-8", errors="replace")
            root = parse("java", source_bytes)
        except Exception as e:
            logger.debug(f"Failed to tree-sitter parse Java {filepath}: {e}")
            return None

        api = FileAnalysis(path=filepath, language="java")

        for node in root.children:
            if node.type == "import_declaration":
                # import com.company.Module;
                name_node = None
                for child in node.children:
                    if child.type in ("identifier", "scoped_identifier"):
                        name_node = child
                        break
                if name_node:
                    raw = node_text(name_node, source_bytes)
                    is_star = False
                    if find_child(node, "asterisk"):
                        raw += ".*"
                        is_star = True

                    top_module = raw.split(".")[0]
                    api.imports.append(ResolvedImport(
                        raw=raw,
                        module=top_module,
                        names=[raw.split(".")[-1]] if not is_star else [],
                        is_relative=False,
                        is_star=is_star,
                    ))

            elif node.type == "class_declaration" or node.type == "interface_declaration":
                cls_info = self._extract_class(node, source_bytes)
                if cls_info:
                    api.classes.append(cls_info)
                    api.exports.append(ExportedSymbol(
                        name=cls_info.name,
                        kind="class" if node.type == "class_declaration" else "interface",
                        is_public=cls_info.is_public
                    ))

        return api

    def _extract_class(self, node, source_bytes: bytes) -> Optional[ClassInfo]:
        name_node = find_child(node, "identifier")
        if not name_node:
            return None
        name = node_text(name_node, source_bytes)

        modifiers_node = find_child(node, "modifiers")
        decorators = self._extract_annotations(modifiers_node, source_bytes)
        
        is_public = False
        is_abstract = False
        if modifiers_node:
            for mod in modifiers_node.children:
                if mod.type == "public":
                    is_public = True
                elif mod.type == "abstract":
                    is_abstract = True

        bases = []
        superclass_node = find_child(node, "superclass")
        if superclass_node:
            t = find_child(superclass_node, "type_identifier")
            if t:
                bases.append(node_text(t, source_bytes))

        super_interfaces = find_child(node, "super_interfaces")
        if super_interfaces:
            for ti in find_children(super_interfaces, "type_identifier"):
                bases.append(node_text(ti, source_bytes))

        methods = []
        body_node = find_child(node, "class_body") or find_child(node, "interface_body")
        if body_node:
            for child in body_node.children:
                if child.type == "method_declaration":
                    m_name_node = find_child(child, "identifier")
                    if m_name_node:
                        methods.append(node_text(m_name_node, source_bytes))

        return ClassInfo(
            name=name,
            bases=bases,
            methods=methods,
            method_count=len(methods),
            decorators=decorators,
            is_abstract=is_abstract,
            is_public=is_public,
            line=node.start_point[0] + 1,
        )

    def _extract_annotations(self, modifiers_node, source_bytes: bytes) -> list[str]:
        if not modifiers_node:
            return []
        decorators = []
        for mod in modifiers_node.children:
            if mod.type in ("marker_annotation", "annotation"):
                n = find_child(mod, "identifier") or find_child(mod, "scoped_identifier")
                if n:
                    decorators.append("@" + node_text(n, source_bytes))
        return decorators
