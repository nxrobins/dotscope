"""Warning explain module: assembles full provenance for a CheckResult."""

import json
import os
from typing import Any, Dict, Optional

from ..models.intent import CheckResult


def explain_warning(root: str, result: CheckResult) -> Dict[str, Any]:
    """Assemble a full explanation for a CheckResult.

    Returns a dict with:
      - source: Which config/data file generated this check
      - rule: The specific rule key
      - rule_text: Extracted text of the rule from the source file
      - evidence: The message + detail from the result
      - precedent_count: How many times this warning has fired before
      - acknowledged_before: Whether this has been previously acknowledged
      - suggestion: Actionable advice
    """
    explanation: Dict[str, Any] = {
        "source": result.source_file or "unknown",
        "rule": result.source_rule or "unknown",
        "rule_text": "",
        "evidence": result.message,
        "detail": result.detail or "",
        "precedent_count": 0,
        "acknowledged_before": False,
        "suggestion": result.suggestion or "",
    }

    # Extract rule text from source file
    if result.source_file and result.source_file not in ("heuristic", "session", "unknown"):
        explanation["rule_text"] = _extract_rule_text(root, result)

    # Count precedents from nudge occurrences
    if result.acknowledge_id:
        explanation["precedent_count"] = _count_precedents(root, result.acknowledge_id)
        explanation["acknowledged_before"] = _was_acknowledged(root, result.acknowledge_id)

    return explanation


def format_explanation(explanation: Dict[str, Any]) -> str:
    """Format an explanation dict as human-readable text."""
    lines = []
    lines.append(f"  Source: {explanation['source']}")
    lines.append(f"  Rule: {explanation['rule']}")
    if explanation.get("rule_text"):
        lines.append(f"  Rule text: {explanation['rule_text']}")
    lines.append(f"  Evidence: {explanation['evidence']}")
    if explanation.get("detail"):
        lines.append(f"  Detail: {explanation['detail']}")
    if explanation["precedent_count"] > 0:
        lines.append(f"  Prior occurrences: {explanation['precedent_count']}")
    if explanation["acknowledged_before"]:
        lines.append("  Previously acknowledged: yes")
    if explanation.get("suggestion"):
        lines.append(f"  Suggestion: {explanation['suggestion']}")
    return "\n".join(lines)


def _extract_rule_text(root: str, result: CheckResult) -> str:
    """Try to extract the specific rule text from the source file."""
    source = result.source_file or ""
    rule = result.source_rule or ""

    if source == "invariants.json":
        return _extract_from_invariants(root, rule)
    if source == "intent.yaml":
        return _extract_from_intents(root, rule)
    if source == "conventions.yaml":
        return _extract_from_conventions(root, rule)
    if source.endswith("/.scope"):
        return _extract_from_scope(root, source, rule)
    if source in ("voice_config", "network_edges"):
        return f"Derived from {source}"

    return ""


def _extract_from_invariants(root: str, rule: str) -> str:
    """Extract contract info from invariants.json."""
    inv_path = os.path.join(root, ".dotscope", "invariants.json")
    try:
        with open(inv_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""

    if rule.startswith("contract:"):
        pair = rule[len("contract:"):]
        for contract in data.get("contracts", []):
            trigger = contract.get("trigger_file", "")
            coupled = contract.get("coupled_file", "")
            if f"{trigger}\u2194{coupled}" == pair or f"{coupled}\u2194{trigger}" == pair:
                desc = contract.get("description", "")
                conf = contract.get("confidence", 0)
                return f"{desc} (confidence: {conf:.0%})" if desc else f"Co-change confidence: {conf:.0%}"

    if rule.startswith("stability:"):
        filepath = rule[len("stability:"):]
        stabilities = data.get("file_stabilities", {})
        info = stabilities.get(filepath, {})
        if info:
            return f"Classification: {info.get('classification', '')}, {info.get('commit_count', 0)} commits"

    return ""


def _extract_from_intents(root: str, rule: str) -> str:
    """Extract intent info from intent.yaml."""
    intent_path = os.path.join(root, "intent.yaml")
    if not os.path.isfile(intent_path):
        intent_path = os.path.join(root, ".dotscope", "intent.yaml")
    try:
        with open(intent_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, OSError):
        return ""

    parts = rule.split(":", 1)
    if len(parts) < 2:
        return ""
    intent_id = parts[1]
    if intent_id in content:
        return f"Intent directive '{parts[0]}' (id: {intent_id})"
    return ""


def _extract_from_conventions(root: str, rule: str) -> str:
    """Extract convention info."""
    if rule.startswith("convention:"):
        name = rule[len("convention:"):]
        return f"Convention: {name}"
    return ""


def _extract_from_scope(root: str, scope_path: str, rule: str) -> str:
    """Extract antipattern info from a .scope file."""
    full_path = os.path.join(root, scope_path)
    if not os.path.isfile(full_path):
        return ""
    if rule.startswith("antipattern:"):
        pattern = rule[len("antipattern:"):]
        return f"Prohibited pattern: {pattern}"
    return ""


def _count_precedents(root: str, acknowledge_id: str) -> int:
    """Count how many times this warning has fired from nudge_occurrences.jsonl."""
    occ_path = os.path.join(root, ".dotscope", "nudge_occurrences.jsonl")
    count = 0
    try:
        with open(occ_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("acknowledge_id") == acknowledge_id:
                        count += 1
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, OSError):
        pass
    return count


def _was_acknowledged(root: str, acknowledge_id: str) -> bool:
    """Check if this warning was previously acknowledged."""
    ack_path = os.path.join(root, ".dotscope", "acknowledgments.jsonl")
    try:
        with open(ack_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("acknowledge_id") == acknowledge_id:
                        return True
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, OSError):
        pass
    return False
