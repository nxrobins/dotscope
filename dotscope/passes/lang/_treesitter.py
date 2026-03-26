"""Tree-sitter utilities: grammar loading, parser caching, query execution."""

from typing import Dict, List, Tuple

try:
    from tree_sitter import Language, Parser, Node

    _languages: Dict[str, Language] = {}
    _parsers: Dict[str, Parser] = {}

    def get_language(name: str) -> Language:
        """Load and cache a tree-sitter Language."""
        if name not in _languages:
            if name == "javascript":
                import tree_sitter_javascript as mod
                _languages[name] = Language(mod.language())
            elif name == "typescript":
                import tree_sitter_typescript as mod
                _languages[name] = Language(mod.language_typescript())
            elif name == "tsx":
                import tree_sitter_typescript as mod
                _languages[name] = Language(mod.language_tsx())
            elif name == "go":
                import tree_sitter_go as mod
                _languages[name] = Language(mod.language())
            else:
                raise ValueError(f"Unknown tree-sitter language: {name}")
        return _languages[name]

    def get_parser(name: str) -> Parser:
        """Return a cached Parser for the given language."""
        if name not in _parsers:
            lang = get_language(name)
            _parsers[name] = Parser(lang)
        return _parsers[name]

    def parse(name: str, source: bytes) -> "Node":
        """Parse source bytes and return the root node."""
        parser = get_parser(name)
        tree = parser.parse(source)
        return tree.root_node

    def node_text(node: "Node", source: bytes) -> str:
        """Extract the text of a node from source bytes."""
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def find_children(node: "Node", type_name: str) -> List["Node"]:
        """Find all direct children of a given type."""
        return [c for c in node.children if c.type == type_name]

    def find_child(node: "Node", type_name: str) -> "Node | None":
        """Find the first direct child of a given type."""
        for c in node.children:
            if c.type == type_name:
                return c
        return None

    def walk_type(node: "Node", type_name: str) -> List["Node"]:
        """Recursively find all descendant nodes of a given type."""
        results = []
        stack = [node]
        while stack:
            n = stack.pop()
            if n.type == type_name:
                results.append(n)
            stack.extend(reversed(n.children))
        return results

    AVAILABLE = True

except ImportError:
    AVAILABLE = False

    def get_language(name):
        raise ImportError("tree-sitter not installed")

    def get_parser(name):
        raise ImportError("tree-sitter not installed")

    def parse(name, source):
        raise ImportError("tree-sitter not installed")

    def node_text(node, source):
        raise ImportError("tree-sitter not installed")

    def find_children(node, type_name):
        raise ImportError("tree-sitter not installed")

    def find_child(node, type_name):
        raise ImportError("tree-sitter not installed")

    def walk_type(node, type_name):
        raise ImportError("tree-sitter not installed")
