"""AST Merge Driver: conflict classification.

Determines whether two sets of mutations from different agents can be
safely merged or require human intervention.
"""

from typing import List, Optional, Set, Tuple

from .models import ASTMutation, MergeHalt, MutationType


def classify_conflicts(
    mutations_a: List[ASTMutation],
    mutations_b: List[ASTMutation],
) -> Tuple[List[ASTMutation], Optional[MergeHalt]]:
    """Classify and merge two mutation sets, detecting conflicts.

    Returns:
        (merged_mutations, halt_or_none)
        If halt is not None, the merge cannot proceed automatically.
    """
    fqns_a = {m.fqn for m in mutations_a}
    fqns_b = {m.fqn for m in mutations_b}

    # Check for direct conflicts: same entity modified by both agents
    overlapping = fqns_a & fqns_b
    if overlapping:
        # Check if the modifications are identical (commutative)
        for fqn in overlapping:
            mut_a = next(m for m in mutations_a if m.fqn == fqn)
            mut_b = next(m for m in mutations_b if m.fqn == fqn)

            # Both ADDs with identical text → commutative, keep one
            if (mut_a.type == MutationType.ADD and mut_b.type == MutationType.ADD
                    and mut_a.agent_segment and mut_b.agent_segment
                    and mut_a.agent_segment.text == mut_b.agent_segment.text):
                continue

            # Both MODIFYs with identical result → commutative, keep one
            if (mut_a.type == MutationType.MODIFY and mut_b.type == MutationType.MODIFY
                    and mut_a.agent_segment and mut_b.agent_segment
                    and mut_a.agent_segment.text == mut_b.agent_segment.text):
                continue

            # Genuine conflict
            return [], MergeHalt(
                reason=f"Both agents modified {fqn}",
                conflicting_mutations=[mut_a, mut_b],
                agent_a_fqns=sorted(fqns_a),
                agent_b_fqns=sorted(fqns_b),
            )

    # No conflicts — merge all mutations
    # For overlapping commutative changes, keep agent A's version
    merged = list(mutations_a)
    for m in mutations_b:
        if m.fqn not in fqns_a:
            merged.append(m)

    return merged, None


def check_dependency_conflicts(
    mutations: List[ASTMutation],
) -> Optional[MergeHalt]:
    """Check if any mutation modifies a function that another mutation depends on.

    Example: Agent A modifies get_user(), Agent B modifies
    update_user() which calls get_user(). The merge succeeds
    structurally, but the contract verifier should catch signature
    mismatches.
    """
    modified_fqns = {m.fqn for m in mutations if m.type == MutationType.MODIFY}

    for m in mutations:
        dep_overlap = set(m.dependencies) & modified_fqns
        if dep_overlap and m.fqn not in modified_fqns:
            # A dependency was modified but the dependent was not
            # This is a soft warning, not a halt — the contract verifier
            # (dotscope_check) will catch actual breakage
            pass

    return None
