"""AST Merge Driver: reconstruction engine.

Applies mutations to the source string losslessly using a dual-pass
approach:

  Pass 1 (Reverse-Order): Applies MODIFY and REMOVE mutations from
  bottom to top, preventing offset drift.

  Pass 2 (Iterative Additions): Re-parses the intermediate source and
  calculates fresh insertion targets using a strict decision tree.
"""

import ast
from typing import List

from .models import ASTMutation, MergeHalt, MutationType, NodeType


def reconstruct_source(
    ancestor_source: str,
    mutations: List[ASTMutation],
) -> str:
    """Apply mutations to the ancestor source, producing the merged result.

    Mutations must have passed pre_flight_checks (no overlapping ranges).
    """
    lines = ancestor_source.splitlines(keepends=True)

    # Separate mutations by type
    modifies = [m for m in mutations if m.type == MutationType.MODIFY]
    removes = [m for m in mutations if m.type == MutationType.REMOVE]
    adds = [m for m in mutations if m.type == MutationType.ADD]

    # Pass 1: Apply MODIFYs and REMOVEs from bottom to top
    replacements = []
    for m in modifies:
        if m.ancestor_segment and m.agent_segment:
            replacements.append((
                m.ancestor_segment.start_line,
                m.ancestor_segment.visual_end_line,
                m.agent_segment.text,
            ))
    for m in removes:
        if m.ancestor_segment:
            replacements.append((
                m.ancestor_segment.start_line,
                m.ancestor_segment.visual_end_line,
                "",  # Remove the segment
            ))

    # Sort by start_line descending to prevent offset drift
    replacements.sort(key=lambda x: x[0], reverse=True)

    for start, end, replacement_text in replacements:
        # Convert to 0-indexed
        start_idx = start - 1
        end_idx = end  # end is inclusive, but slicing is exclusive
        if replacement_text:
            replacement_lines = replacement_text.splitlines(keepends=True)
        else:
            replacement_lines = []
        lines[start_idx:end_idx] = replacement_lines

    intermediate = "".join(lines)

    # Pass 2: Apply ADDs with fresh insertion targets
    if adds:
        intermediate = _apply_additions(intermediate, adds)

    return intermediate


def _apply_additions(source: str, additions: List[ASTMutation]) -> str:
    """Insert new entities into the source at appropriate locations.

    Decision tree for insertion targets:
      - New module-level assignment: after last import, before first function/class
      - New top-level function: before __main__ guard, or EOF
      - New method: after target class's last method
    """
    for add in additions:
        if not add.agent_segment:
            continue

        lines = source.splitlines(keepends=True)

        if add.node_type == NodeType.METHOD:
            # Find target class and insert after its last line
            source = _insert_method(source, add)
        elif add.node_type == NodeType.FUNCTION:
            # Insert before __main__ guard or at EOF
            source = _insert_function(source, add)
        elif add.node_type in (NodeType.ASSIGNMENT, NodeType.IMPORT):
            # Insert after last import
            source = _insert_after_imports(source, add)
        else:
            # Default: append to end
            source = source.rstrip("\n") + "\n\n\n" + add.agent_segment.text

    return source


def _insert_function(source: str, add: ASTMutation) -> str:
    """Insert a top-level function before __main__ guard or at EOF."""
    lines = source.splitlines(keepends=True)

    # Look for if __name__ == "__main__":
    main_line = None
    try:
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.If) and _is_main_guard(node):
                main_line = node.lineno - 1  # 0-indexed
                break
    except SyntaxError:
        pass

    text = add.agent_segment.text
    if not text.endswith("\n"):
        text += "\n"

    if main_line is not None:
        # Insert before __main__ with two blank lines separation
        lines.insert(main_line, "\n\n" + text + "\n")
    else:
        # Append to EOF with two blank lines
        source = source.rstrip("\n") + "\n\n\n" + text
        return source

    return "".join(lines)


def _insert_method(source: str, add: ASTMutation) -> str:
    """Insert a method into its target class."""
    # Extract class name from FQN: "MyClass.new_method" → "MyClass"
    parts = add.fqn.split(".", 1)
    if len(parts) < 2:
        return source + "\n\n" + add.agent_segment.text

    class_name = parts[0]

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source + "\n\n" + add.agent_segment.text

    lines = source.splitlines(keepends=True)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            insert_line = (node.end_lineno or node.lineno)

            # Detect indentation from existing methods
            indent = "    "  # default
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    indent = " " * (child.col_offset or 4)
                    break

            # Re-indent the method text
            method_lines = add.agent_segment.text.splitlines(keepends=True)
            reindented = []
            for ml in method_lines:
                stripped = ml.lstrip()
                if stripped:
                    reindented.append(indent + stripped)
                else:
                    reindented.append(ml)

            insert_text = "\n" + "".join(reindented)
            lines.insert(insert_line, insert_text)
            return "".join(lines)

    # Class not found — append at end
    return source + "\n\n" + add.agent_segment.text


def _insert_after_imports(source: str, add: ASTMutation) -> str:
    """Insert after the last import statement."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return add.agent_segment.text + "\n" + source

    lines = source.splitlines(keepends=True)
    last_import_line = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_line = max(last_import_line, node.end_lineno or node.lineno)

    text = add.agent_segment.text
    if not text.endswith("\n"):
        text += "\n"

    lines.insert(last_import_line, "\n" + text)
    return "".join(lines)


def _is_main_guard(node: ast.If) -> bool:
    """Check if an If node is `if __name__ == "__main__":`."""
    try:
        test = node.test
        if isinstance(test, ast.Compare):
            if isinstance(test.left, ast.Name) and test.left.id == "__name__":
                if test.comparators and isinstance(test.comparators[0], ast.Constant):
                    return test.comparators[0].value == "__main__"
    except Exception:
        pass
    return False
