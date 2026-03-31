"""AST Merge Driver: mutation extraction and visual boundary computation.

Diffs flat lists of named entities (functions, classes) instead of raw
AST trees. Calculates exact visual boundaries including trailing whitespace
and enforces overlap guards.
"""

import ast
from typing import Dict, List, Optional, Tuple

from .models import ASTMutation, MergeHalt, MutationType, NodeType, SourceSegment


def extract_mutations(
    ancestor_source: str,
    agent_source: str,
) -> List[ASTMutation]:
    """Extract structural mutations between ancestor and agent versions.

    Compares named entities (functions, classes, methods, assignments)
    and produces a flat list of ADD/MODIFY/REMOVE mutations.
    """
    ancestor_entities = _extract_entities(ancestor_source)
    agent_entities = _extract_entities(agent_source)

    ancestor_lines = ancestor_source.splitlines(keepends=True)
    agent_lines = agent_source.splitlines(keepends=True)

    mutations = []

    # Find MODIFYs and REMOVEs
    for fqn, (node_type, start, end) in ancestor_entities.items():
        visual_end = _compute_visual_end(end, ancestor_lines, ancestor_entities, fqn)
        ancestor_seg = SourceSegment(
            start_line=start,
            end_line=end,
            visual_end_line=visual_end,
            text="".join(ancestor_lines[start - 1:visual_end]),
        )

        if fqn in agent_entities:
            a_node_type, a_start, a_end = agent_entities[fqn]
            a_visual_end = _compute_visual_end(a_end, agent_lines, agent_entities, fqn)
            agent_seg = SourceSegment(
                start_line=a_start,
                end_line=a_end,
                visual_end_line=a_visual_end,
                text="".join(agent_lines[a_start - 1:a_visual_end]),
            )

            if ancestor_seg.text != agent_seg.text:
                mutations.append(ASTMutation(
                    type=MutationType.MODIFY,
                    node_type=node_type,
                    fqn=fqn,
                    ancestor_segment=ancestor_seg,
                    agent_segment=agent_seg,
                ))
        else:
            mutations.append(ASTMutation(
                type=MutationType.REMOVE,
                node_type=node_type,
                fqn=fqn,
                ancestor_segment=ancestor_seg,
            ))

    # Find ADDs
    for fqn, (node_type, start, end) in agent_entities.items():
        if fqn not in ancestor_entities:
            visual_end = _compute_visual_end(end, agent_lines, agent_entities, fqn)
            agent_seg = SourceSegment(
                start_line=start,
                end_line=end,
                visual_end_line=visual_end,
                text="".join(agent_lines[start - 1:visual_end]),
            )
            mutations.append(ASTMutation(
                type=MutationType.ADD,
                node_type=node_type,
                fqn=fqn,
                agent_segment=agent_seg,
            ))

    return mutations


def pre_flight_checks(mutations: List[ASTMutation]) -> Optional[MergeHalt]:
    """Halt if any two mutation visual ranges overlap.

    This catches cases where two agents modified adjacent functions
    and their visual boundaries (including trailing whitespace) collide.
    """
    # Collect all ancestor segments that will be replaced
    segments = []
    for mut in mutations:
        if mut.ancestor_segment:
            segments.append((mut.ancestor_segment.start_line,
                             mut.ancestor_segment.visual_end_line, mut))

    segments.sort(key=lambda x: x[0])

    for i in range(len(segments) - 1):
        _, end_a, mut_a = segments[i]
        start_b, _, mut_b = segments[i + 1]
        if end_a >= start_b:
            return MergeHalt(
                reason=f"Overlapping visual ranges: {mut_a.fqn} (ends {end_a}) "
                       f"overlaps {mut_b.fqn} (starts {start_b})",
                conflicting_mutations=[mut_a, mut_b],
            )

    return None


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _extract_entities(
    source: str,
) -> Dict[str, Tuple[NodeType, int, int]]:
    """Extract named entities with their line ranges.

    Returns: {fqn: (node_type, start_line, end_line)}
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    entities: Dict[str, Tuple[NodeType, int, int]] = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            entities[node.name] = (NodeType.FUNCTION, node.lineno, node.end_lineno or node.lineno)
        elif isinstance(node, ast.ClassDef):
            entities[node.name] = (NodeType.CLASS, node.lineno, node.end_lineno or node.lineno)
            # Also extract methods
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fqn = f"{node.name}.{child.name}"
                    entities[fqn] = (NodeType.METHOD, child.lineno, child.end_lineno or child.lineno)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    entities[target.id] = (NodeType.ASSIGNMENT, node.lineno, node.end_lineno or node.lineno)

    return entities


def _compute_visual_end(
    node_end_lineno: int,
    source_lines: List[str],
    entities: Dict[str, tuple],
    current_fqn: str,
) -> int:
    """Compute the visual end of a node, consuming trailing blank lines.

    Scans forward from the AST end_lineno until hitting the next named
    entity or a non-blank line, or EOF.
    """
    # Find the next entity's start line
    next_starts = []
    for fqn, (_, start, _) in entities.items():
        if fqn != current_fqn and start > node_end_lineno:
            next_starts.append(start)

    next_start = min(next_starts) if next_starts else len(source_lines) + 1

    # Consume trailing blank lines up to (but not including) next entity
    visual_end = node_end_lineno
    for i in range(node_end_lineno, min(next_start - 1, len(source_lines))):
        if source_lines[i].strip() == "":
            visual_end = i + 1  # 1-indexed
        else:
            break

    return visual_end
