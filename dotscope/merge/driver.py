"""Git merge driver CLI entry point.

Registered via: git config merge.dotscope-ast.driver "python3 -m dotscope.merge.driver %O %A %B"

Git passes three temp files:
  %O = ancestor (common base)
  %A = ours (current branch)
  %B = theirs (incoming branch)

The driver writes the merged result back to %A (Git convention).
Exit 0 = merge succeeded. Exit 1 = conflict (Git falls back to standard markers).
"""

import sys
from pathlib import Path


def main() -> int:
    """Run the 3-way AST merge."""
    if len(sys.argv) != 4:
        print("Usage: python3 -m dotscope.merge.driver <ancestor> <ours> <theirs>",
              file=sys.stderr)
        return 1

    ancestor_path = Path(sys.argv[1])
    ours_path = Path(sys.argv[2])
    theirs_path = Path(sys.argv[3])

    try:
        ancestor = ancestor_path.read_text(encoding="utf-8")
        ours = ours_path.read_text(encoding="utf-8")
        theirs = theirs_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError) as e:
        print(f"dotscope merge: cannot read inputs: {e}", file=sys.stderr)
        return 1  # Fall back to Git's default merger

    # Trivial cases
    if ours == theirs:
        return 0  # Both sides identical — nothing to merge
    if ours == ancestor:
        # Only theirs changed — take theirs
        ours_path.write_text(theirs, encoding="utf-8")
        return 0
    if theirs == ancestor:
        # Only ours changed — keep ours
        return 0

    # Full 3-way merge
    try:
        result = merge_three_way(ancestor, ours, theirs)
    except Exception as e:
        print(f"dotscope merge: internal error: {e}", file=sys.stderr)
        return 1

    if not result.success:
        for halt in result.halts:
            print(f"dotscope merge: CONFLICT — {halt.reason}", file=sys.stderr)
        return 1

    # Write merged result back to %A
    ours_path.write_text(result.merged_source, encoding="utf-8")
    return 0


def merge_three_way(ancestor: str, ours: str, theirs: str):
    """Perform a full 3-way semantic merge.

    1. Extract mutations: ancestor→ours (Agent A) and ancestor→theirs (Agent B)
    2. Classify conflicts between the two mutation sets
    3. Resolve imports using 3-way set logic
    4. Apply merged mutations via dual-pass reconstruction
    5. Run contract verification on the result
    """
    from .differ import extract_mutations, pre_flight_checks
    from .classifier import classify_conflicts
    from .imports import resolve_imports
    from .composer import reconstruct_source
    from .models import MergeResult, MergeHalt

    # Step 1: Extract mutations
    mutations_a = extract_mutations(ancestor, ours)
    mutations_b = extract_mutations(ancestor, theirs)

    # Step 2: Classify conflicts
    merged_mutations, halt = classify_conflicts(mutations_a, mutations_b)
    if halt:
        return MergeResult(success=False, halts=[halt])

    # Step 3: Pre-flight overlap check
    overlap_halt = pre_flight_checks(merged_mutations)
    if overlap_halt:
        return MergeResult(success=False, halts=[overlap_halt])

    # Step 4: Resolve imports
    merged_imports = resolve_imports(ancestor, ours, theirs)
    imports_resolved = len(merged_imports)

    # Step 5: Apply mutations
    merged_source = reconstruct_source(ancestor, merged_mutations)

    # Step 6: Replace import block with merged imports
    merged_source = _replace_import_block(merged_source, merged_imports)

    return MergeResult(
        success=True,
        merged_source=merged_source,
        mutations_applied=len(merged_mutations),
        imports_resolved=imports_resolved,
    )


def _replace_import_block(source: str, merged_imports: list) -> str:
    """Replace the import section of source with merged imports."""
    import ast

    if not merged_imports:
        return source

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    lines = source.splitlines(keepends=True)

    # Find import range
    first_import = None
    last_import = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if first_import is None:
                first_import = node.lineno
            last_import = node.end_lineno or node.lineno

    if first_import is None:
        return source

    # Replace import range with merged imports
    import_text = "\n".join(merged_imports) + "\n"
    before = lines[:first_import - 1]
    after = lines[last_import:]

    return "".join(before) + import_text + "".join(after)


if __name__ == "__main__":
    sys.exit(main())
