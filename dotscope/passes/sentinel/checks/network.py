"""Network contract check: backend changes must update their frontend consumers.

Severity is determined by match confidence:
  - Confidence >= 0.8 (exact regex or suffix match): HOLD — hard block.
    The agent must update the consumer or acknowledge "payload unchanged".
  - Confidence == 0.5 (semantic root substring match): NOTE — soft warning.
    Lower confidence means the link may be a false positive (e.g.,
    UserViewSet matching /api/user-settings/ by substring).
"""

from typing import Dict, List, Optional, Tuple

from ..models import CheckCategory, CheckResult, Severity


def check_network_contracts(
    modified_files: List[str],
    network_edges: Dict[str, Dict[str, list]],
    network_confidence: Optional[Dict[Tuple[str, str], float]] = None,
) -> List[CheckResult]:
    """Check if modified backend endpoints have unupdated frontend consumers.

    Args:
        modified_files: Relative paths of files changed in the diff.
        network_edges: {provider_file: {consumer_file: [endpoint_info]}}.
        network_confidence: {(provider, consumer): confidence} from the linker.
    """
    if not network_edges:
        return []

    results = []
    modified_set = set(modified_files)
    confidence = network_confidence or {}

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

        # Determine severity from confidence
        # Max confidence across all unmodified consumers for this provider
        max_conf = max(
            confidence.get((filepath, c), 1.0)  # default to 1.0 if no confidence data
            for c in unmodified
        )

        if max_conf >= 0.8:
            severity = Severity.HOLD
            severity_label = "HOLD"
        else:
            severity = Severity.NOTE
            severity_label = "NOTE (low-confidence link)"

        results.append(CheckResult(
            passed=False,
            category=CheckCategory.NETWORK,
            severity=severity,
            message=f"Unresolved Network Contract ({severity_label}): {filepath}",
            detail=(
                f"You modified backend endpoints ({ep_label}) in {filepath}.\n"
                f"These routes are consumed by frontend files that were not updated:\n"
                f"{consumer_list}\n"
                f"Match confidence: {max_conf:.1f}\n\n"
                f"If the payload or contract changed, you must update the consumers.\n"
                f"If this is an internal refactor with no payload change, acknowledge it."
            ),
            file=filepath,
            suggestion=f"Update the consumer(s) above, or: dotscope check --acknowledge <id> \"Payload unchanged\"",
            can_acknowledge=True,
            acknowledge_id=f"network_{filepath.replace('/', '_').replace('.', '_')}",
        ))

    return results
