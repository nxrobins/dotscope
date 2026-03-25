"""Architectural intent: declare where the codebase is trying to go.

intent.yaml lives at repo root alongside .scopes:

    intents:
      - directive: decouple
        modules: [auth/, payments/]
        reason: "Auth should not depend on payment internals"
        set_by: developer
        set_at: 2026-03-20
"""

import hashlib
import os
from typing import List, Optional

from .check.models import IntentDirective


def load_intents(repo_root: str) -> List[IntentDirective]:
    """Load intent.yaml from repo root."""
    path = os.path.join(repo_root, "intent.yaml")
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    raw_intents = _parse_intent_list(text)
    results = []

    for item in raw_intents:
        directive = item.get("directive", "")
        if directive not in ("decouple", "deprecate", "freeze", "consolidate"):
            continue

        modules = _to_list(item.get("modules", []))
        files = _to_list(item.get("files", []))
        reason = item.get("reason", "").strip('"').strip("'")
        slug = hashlib.md5(
            f"{directive}:{','.join(modules + files)}".encode()
        ).hexdigest()[:8]

        results.append(IntentDirective(
            directive=directive,
            modules=modules,
            files=files,
            reason=reason,
            replacement=item.get("replacement"),
            target=item.get("target"),
            set_by=item.get("set_by", "developer"),
            set_at=item.get("set_at", ""),
            id=slug,
        ))

    return results


def _parse_intent_list(text: str) -> List[dict]:
    """Parse the intents list from intent.yaml.

    Handles the specific pattern:
        intents:
          - directive: freeze
            modules: [core/]
            reason: "Stable"
    """
    items = []
    current: Optional[dict] = None
    in_intents = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "intents:" or stripped.startswith("intents:"):
            in_intents = True
            continue

        if not in_intents:
            continue

        indent = len(line) - len(line.lstrip())

        if stripped.startswith("- "):
            # New list item
            if current is not None:
                items.append(current)
            current = {}
            # Parse the key-value on the same line as the dash
            kv = stripped[2:].strip()
            if ":" in kv:
                k, v = kv.split(":", 1)
                current[k.strip()] = _parse_value(v.strip())
        elif current is not None and ":" in stripped and indent >= 4:
            k, v = stripped.split(":", 1)
            current[k.strip()] = _parse_value(v.strip())
        elif indent == 0 and not stripped.startswith("-"):
            # New top-level key — we've left the intents block
            break

    if current is not None:
        items.append(current)

    return items


def _parse_value(val: str) -> object:
    """Parse a YAML value: inline list, quoted string, or plain string."""
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1]
        return [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def save_intents(repo_root: str, intents: List[IntentDirective]) -> str:
    """Write intents to intent.yaml."""
    lines = ["intents:"]
    for intent in intents:
        lines.append(f"  - directive: {intent.directive}")
        if intent.modules:
            items = ", ".join(intent.modules)
            lines.append(f"    modules: [{items}]")
        if intent.files:
            items = ", ".join(intent.files)
            lines.append(f"    files: [{items}]")
        if intent.replacement:
            lines.append(f"    replacement: {intent.replacement}")
        if intent.target:
            lines.append(f"    target: {intent.target}")
        if intent.reason:
            lines.append(f'    reason: "{intent.reason}"')
        lines.append(f"    set_by: {intent.set_by}")
        if intent.set_at:
            lines.append(f"    set_at: {intent.set_at}")

    path = os.path.join(repo_root, "intent.yaml")
    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def add_intent(
    repo_root: str,
    directive: str,
    targets: List[str],
    reason: str = "",
    replacement: Optional[str] = None,
    target: Optional[str] = None,
) -> IntentDirective:
    """Add a new intent and persist to intent.yaml."""
    from datetime import date

    existing = load_intents(repo_root)

    # Classify targets as modules (end with /) or files
    modules = [t for t in targets if t.endswith("/")]
    files = [t for t in targets if not t.endswith("/")]

    slug = hashlib.md5(
        f"{directive}:{','.join(modules + files)}".encode()
    ).hexdigest()[:8]

    intent = IntentDirective(
        directive=directive,
        modules=modules,
        files=files,
        reason=reason,
        replacement=replacement,
        target=target,
        set_by="developer",
        set_at=str(date.today()),
        id=slug,
    )

    existing.append(intent)
    save_intents(repo_root, existing)
    return intent


def remove_intent(repo_root: str, intent_id: str) -> bool:
    """Remove an intent by its ID."""
    existing = load_intents(repo_root)
    filtered = [i for i in existing if i.id != intent_id]
    if len(filtered) == len(existing):
        return False
    save_intents(repo_root, filtered)
    return True


def _to_list(val: object) -> List[str]:
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str) and val:
        return [val]
    return []
