"""Network contract check: backend changes must update their frontend consumers.

If an agent modifies a file that serves HTTP endpoints consumed by frontend
files, and those frontend files are NOT in the diff, this is a HOLD — the
commit is blocked until the agent either updates the consumer or explicitly
acknowledges that the payload contract is unchanged.

Why HOLD (not NUDGE): AI agents ignore non-blocking warnings. A NUDGE lets
the agent sail past a broken contract into production. HOLD forces the
agent's execution loop to stop. If the payload truly didn't change, the
agent runs ``dotscope check --acknowledge <id> "Payload unchanged"``
creating a permanent audit trail.
"""

from typing import Dict, List

from ..models import CheckCategory, CheckResult, Severity


def check_network_contracts(
    modified_files: List[str],
    network_edges: Dict[str, Dict[str, list]],
) -> List[CheckResult]:
    """Check if modified backend endpoints have unupdated frontend consumers.

    Args:
        modified_files: Relative paths of files changed in the diff.
        network_edges: {provider_file: {consumer_file: [endpoint_info]}}.
    """
    if not network_edges:
        return []

    results = []
    modified_set = set(modified_files)

    for filepath in modified_files:
        consumers = network_edges.get(filepath)
        if not consumers:
            continue

        # This file is an API provider. Check if consumers were also modified.
        unmodified = [c for c in consumers if c not in modified_set]
        if not unmodified:
            continue  # All consumers updated — contract satisfied

        # Build endpoint names for the message
        all_endpoints = []
        for consumer_path in unmodified:
            for ep_info in consumers[consumer_path]:
                name = ep_info.get("handler", "") if isinstance(ep_info, dict) else getattr(ep_info, "handler_name", "")
                if name and name not in all_endpoints:
                    all_endpoints.append(name)

        ep_label = ", ".join(all_endpoints[:3]) or "endpoints"
        consumer_list = "\n".join(f"  - {c}" for c in unmodified[:5])
        if len(unmodified) > 5:
            consumer_list += f"\n  ... and {len(unmodified) - 5} more"

        results.append(CheckResult(
            passed=False,
            category=CheckCategory.NETWORK,
            severity=Severity.HOLD,
            message=f"Unresolved Network Contract: {filepath}",
            detail=(
                f"You modified backend endpoints ({ep_label}) in {filepath}.\n"
                f"These routes are consumed by frontend files that were not updated:\n"
                f"{consumer_list}\n\n"
                f"If the payload or contract changed, you must update the consumers.\n"
                f"If this is an internal refactor with no payload change, acknowledge it."
            ),
            file=filepath,
            suggestion=f"Update the consumer(s) above, or: dotscope check --acknowledge <id> \"Payload unchanged\"",
            can_acknowledge=True,
            acknowledge_id=f"network_{filepath.replace('/', '_').replace('.', '_')}",
        ))

    return results
