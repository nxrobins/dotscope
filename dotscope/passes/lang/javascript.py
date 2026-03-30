"""Tree-sitter JavaScript/TypeScript analyzer.

Produces the same FileAnalysis shape as the Python stdlib ast analyzer.
A single class handles both JS and TS since TS is a superset — TS-only
features (decorators, type annotations) simply produce no captures on
plain JS files.
"""

import os
from typing import List, Optional

from ._base import BaseAnalyzer
from ._treesitter import (
    parse, node_text, find_child, find_children, walk_type
)
from ...models.core import (
    FileAnalysis, ResolvedImport, ClassInfo, FunctionInfo, ExportedSymbol,
    NetworkConsumer,
)


class JavaScriptAnalyzer(BaseAnalyzer):

    def analyze(self, filepath: str, source: str) -> Optional[FileAnalysis]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".tsx",):
            lang = "tsx"
        elif ext in (".ts",):
            lang = "typescript"
        else:
            lang = "javascript"

        source_bytes = source.encode("utf-8")
        try:
            root = parse(lang, source_bytes)
        except Exception:
            return None

        imports = self._extract_imports(root, source_bytes)
        classes = self._extract_classes(root, source_bytes)
        functions = self._extract_functions(root, source_bytes)
        exports = self._extract_exports(root, source_bytes)
        decorators = self._extract_all_decorators(root, source_bytes)
        consumers = self._extract_network_consumers(root, source_bytes, filepath)
        docstring = self._extract_module_docstring(root, source_bytes)

        return FileAnalysis(
            path=filepath,
            language="typescript" if ext in (".ts", ".tsx") else "javascript",
            imports=imports,
            classes=classes,
            functions=functions,
            exports=exports,
            decorators_used=sorted(set(decorators)),
            network_consumers=consumers,
            docstring=docstring,
            node_count=self._count_nodes(root),
        )

    def _extract_imports(self, root, source_bytes) -> List[ResolvedImport]:
        imports = []

        # ES imports: import X from '...', import { X } from '...', import * as X from '...'
        for node in find_children(root, "import_statement"):
            source_node = find_child(node, "string")
            if not source_node:
                continue
            raw = _strip_quotes(node_text(source_node, source_bytes))

            clause = find_child(node, "import_clause")
            names = []
            is_star = False
            if clause:
                for named in walk_type(clause, "import_specifier"):
                    name_node = find_child(named, "identifier")
                    if name_node:
                        names.append(node_text(name_node, source_bytes))
                for ns in walk_type(clause, "namespace_import"):
                    is_star = True
                    id_node = find_child(ns, "identifier")
                    if id_node:
                        names.append(node_text(id_node, source_bytes))
                # default import
                default_id = find_child(clause, "identifier")
                if default_id and default_id.parent == clause:
                    names.append(node_text(default_id, source_bytes))

            imports.append(ResolvedImport(
                raw=raw,
                module=raw.split("/")[-1] if "/" in raw else raw,
                names=names,
                is_star=is_star,
                is_relative=raw.startswith("."),
                line=node.start_point[0] + 1,
            ))

        # require() calls
        for call in walk_type(root, "call_expression"):
            fn = find_child(call, "identifier")
            if fn and node_text(fn, source_bytes) == "require":
                args = find_child(call, "arguments")
                if args:
                    str_node = find_child(args, "string")
                    if str_node:
                        raw = _strip_quotes(node_text(str_node, source_bytes))
                        imports.append(ResolvedImport(
                            raw=raw,
                            module=raw.split("/")[-1] if "/" in raw else raw,
                            names=[],
                            is_relative=raw.startswith("."),
                            line=call.start_point[0] + 1,
                        ))

        # dynamic import()
        for call in walk_type(root, "call_expression"):
            fn = find_child(call, "import")
            if fn:
                args = find_child(call, "arguments")
                if args:
                    str_node = find_child(args, "string")
                    if str_node:
                        raw = _strip_quotes(node_text(str_node, source_bytes))
                        imports.append(ResolvedImport(
                            raw=raw,
                            module=raw.split("/")[-1] if "/" in raw else raw,
                            names=[],
                            is_conditional=True,
                            is_relative=raw.startswith("."),
                            line=call.start_point[0] + 1,
                        ))

        return imports

    def _extract_classes(self, root, source_bytes) -> List[ClassInfo]:
        classes = []
        for node in walk_type(root, "class_declaration"):
            classes.append(self._parse_class(node, source_bytes))
        # class expressions assigned to variables
        for node in walk_type(root, "class"):
            if node.parent and node.parent.type != "class_declaration":
                classes.append(self._parse_class(node, source_bytes))
        return classes

    def _parse_class(self, node, source_bytes) -> ClassInfo:
        name = ""
        name_node = find_child(node, "identifier") or find_child(node, "type_identifier")
        if name_node:
            name = node_text(name_node, source_bytes)

        # Base classes (extends)
        bases = []
        heritage = find_child(node, "class_heritage")
        if heritage:
            # member_expression: React.Component (check first, more specific)
            mem = find_child(heritage, "member_expression")
            if mem:
                bases.append(node_text(mem, source_bytes))
            else:
                # Simple identifier: BaseService
                id_node = find_child(heritage, "identifier")
                if id_node:
                    bases.append(node_text(id_node, source_bytes))

        # Methods
        methods = []
        body = find_child(node, "class_body")
        if body:
            for method in find_children(body, "method_definition"):
                method_name = find_child(method, "property_identifier")
                if method_name:
                    methods.append(node_text(method_name, source_bytes))

        # Decorators (TS)
        decorators = []
        for dec in find_children(node, "decorator"):
            dec_text = node_text(dec, source_bytes).lstrip("@").split("(")[0]
            decorators.append(dec_text)
        # Also check preceding siblings (some grammars put decorators before the class)
        if node.prev_named_sibling and node.prev_named_sibling.type == "decorator":
            dec_text = node_text(node.prev_named_sibling, source_bytes).lstrip("@").split("(")[0]
            decorators.append(dec_text)

        return ClassInfo(
            name=name,
            bases=bases,
            methods=methods,
            method_count=len(methods),
            decorators=decorators,
            is_public=True,
            line=node.start_point[0] + 1,
        )

    def _extract_functions(self, root, source_bytes) -> List[FunctionInfo]:
        functions = []

        # Top-level function declarations
        for node in find_children(root, "function_declaration"):
            functions.append(self._parse_function(node, source_bytes))

        # Exported function declarations
        for export in find_children(root, "export_statement"):
            for fn in find_children(export, "function_declaration"):
                functions.append(self._parse_function(fn, source_bytes))

        # Arrow functions assigned to top-level const/let/var
        for decl in find_children(root, "lexical_declaration"):
            for declarator in find_children(decl, "variable_declarator"):
                value = find_child(declarator, "arrow_function")
                if value:
                    name_node = find_child(declarator, "identifier")
                    name = node_text(name_node, source_bytes) if name_node else ""
                    functions.append(self._parse_arrow(name, value, source_bytes))

        return functions

    def _parse_function(self, node, source_bytes) -> FunctionInfo:
        name = ""
        name_node = find_child(node, "identifier")
        if name_node:
            name = node_text(name_node, source_bytes)

        params = self._extract_params(node, source_bytes)
        return_type = self._extract_return_type(node, source_bytes)
        is_async = any(
            c.type == "async" for c in node.children
        )

        decorators = []
        if node.prev_named_sibling and node.prev_named_sibling.type == "decorator":
            dec_text = node_text(node.prev_named_sibling, source_bytes).lstrip("@").split("(")[0]
            decorators.append(dec_text)

        return FunctionInfo(
            name=name,
            params=params,
            arg_count=len(params),
            return_type=return_type,
            decorators=decorators,
            is_async=is_async,
            is_public=True,
            line=node.start_point[0] + 1,
        )

    def _parse_arrow(self, name, node, source_bytes) -> FunctionInfo:
        params = self._extract_params(node, source_bytes)
        return_type = self._extract_return_type(node, source_bytes)
        is_async = any(c.type == "async" for c in node.children)

        return FunctionInfo(
            name=name,
            params=params,
            arg_count=len(params),
            return_type=return_type,
            is_async=is_async,
            is_public=True,
            line=node.start_point[0] + 1,
        )

    def _extract_params(self, node, source_bytes) -> List[str]:
        params_node = find_child(node, "formal_parameters")
        if not params_node:
            return []
        params = []
        for child in params_node.children:
            if child.type in ("identifier", "required_parameter",
                              "optional_parameter", "rest_parameter",
                              "assignment_pattern"):
                params.append(node_text(child, source_bytes))
        return params

    def _extract_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract TS return type annotation."""
        for child in node.children:
            if child.type == "type_annotation":
                return node_text(child, source_bytes).lstrip(": ").strip()
        return None

    def _extract_exports(self, root, source_bytes) -> List[ExportedSymbol]:
        exports = []
        for node in find_children(root, "export_statement"):
            # export default X
            default_node = find_child(node, "identifier")
            fn = find_child(node, "function_declaration")
            cls = find_child(node, "class_declaration")

            if fn:
                name_node = find_child(fn, "identifier")
                if name_node:
                    exports.append(ExportedSymbol(
                        name=node_text(name_node, source_bytes),
                        kind="function",
                    ))
            elif cls:
                name_node = find_child(cls, "identifier")
                if name_node:
                    exports.append(ExportedSymbol(
                        name=node_text(name_node, source_bytes),
                        kind="class",
                    ))
            elif default_node and any(c.type == "default" for c in node.children):
                exports.append(ExportedSymbol(
                    name=node_text(default_node, source_bytes),
                    kind="variable",
                ))

            # export const/let/var
            for decl in find_children(node, "lexical_declaration"):
                for declarator in find_children(decl, "variable_declarator"):
                    id_node = find_child(declarator, "identifier")
                    if id_node:
                        exports.append(ExportedSymbol(
                            name=node_text(id_node, source_bytes),
                            kind="variable",
                        ))

        return exports

    def _extract_all_decorators(self, root, source_bytes) -> List[str]:
        """Collect all decorator names used in the file."""
        decorators = []
        for dec in walk_type(root, "decorator"):
            text = node_text(dec, source_bytes).lstrip("@").split("(")[0]
            decorators.append(text)
        return decorators

    # -- Polyglot Context: network consumer extraction --

    _HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "request"}

    def _extract_network_consumers(
        self, root, source_bytes, filepath: str
    ) -> List[NetworkConsumer]:
        """Extract HTTP client calls (fetch, axios, api.get, etc.)."""
        import re as _re
        consumers: List[NetworkConsumer] = []

        for call_node in walk_type(root, "call_expression"):
            func = find_child(call_node, "member_expression")
            func_id = find_child(call_node, "identifier")
            method = "GET"
            is_http_call = False

            if func:
                # Pattern: axios.post("/path"), api.get("/path"), apiClient.delete("/path")
                prop = find_child(func, "property_identifier")
                if prop:
                    prop_text = node_text(prop, source_bytes).lower()
                    if prop_text in self._HTTP_METHODS:
                        method = prop_text.upper()
                        if method == "REQUEST":
                            method = "ALL"
                        is_http_call = True
            elif func_id:
                # Pattern: fetch("/path")
                id_text = node_text(func_id, source_bytes)
                if id_text == "fetch":
                    is_http_call = True
                    method = "GET"  # Default; could be overridden by options

            if not is_http_call:
                continue

            # Extract the first string or template_string argument
            args = find_child(call_node, "arguments")
            if not args:
                continue

            raw_path = None
            for child in args.children:
                if child.type in ("string", "template_string"):
                    raw_path = _strip_quotes(node_text(child, source_bytes))
                    break

            if not raw_path or not raw_path.startswith("/"):
                continue  # Not an absolute path — skip relative or variable-only

            # Convert JS template variables ${...} → [^/]+ regex
            # Same language as Python's {var} → [^/]+
            regex_path = _re.sub(r"\$\{[^}]*\}", "[^/]+", raw_path)
            # Escape remaining regex-special chars, protect wildcards
            parts = _re.split(r"(\[\^/\]\+)", regex_path)
            escaped = []
            for part in parts:
                if part == "[^/]+":
                    escaped.append(part)
                else:
                    escaped.append(_re.escape(part))
            regex_path = "^" + "".join(escaped) + "$"

            consumers.append(NetworkConsumer(
                method=method,
                raw_path=raw_path,
                regex_path=regex_path,
                file=filepath,
            ))

        return consumers

    def _extract_module_docstring(self, root, source_bytes) -> Optional[str]:
        """Extract leading JSDoc comment as module docstring."""
        if root.child_count == 0:
            return None
        first = root.children[0]
        if first.type == "comment":
            text = node_text(first, source_bytes)
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


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string literal."""
    if len(s) >= 2 and s[0] in ('"', "'", "`") and s[-1] in ('"', "'", "`"):
        return s[1:-1]
    return s
