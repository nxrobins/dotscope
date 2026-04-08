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

from ..models.intent import ConventionRule, IntentDirective
from ..ux.textio import read_repo_text


def load_intents(repo_root: str) -> List[IntentDirective]:
    """Load intent.yaml from repo root."""
    path = os.path.join(repo_root, "intent.yaml")
    if not os.path.exists(path):
        return []

    text = read_repo_text(path).text

    raw_intents = _parse_intent_list(text)
    results = []

    _valid_directives = ("decouple", "deprecate", "freeze", "consolidate")
    for item in raw_intents:
        directive = item.get("directive", "")
        if directive not in _valid_directives:
            if directive:
                import sys
                print(
                    f"dotscope: unknown directive '{directive}' in intent.yaml, skipping",
                    file=sys.stderr,
                )
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


# ---------------------------------------------------------------------------
# Convention loading/saving
# ---------------------------------------------------------------------------

def load_conventions(repo_root: str) -> List[ConventionRule]:
    """Load conventions from intent.yaml."""
    path = os.path.join(repo_root, "intent.yaml")
    if not os.path.exists(path):
        return []

    text = read_repo_text(path).text

    raw = _parse_conventions_list(text)
    results = []

    for item in raw:
        name = item.get("name", "")
        if not name:
            continue

        match_criteria = {}
        match_block = item.get("match", {})
        if isinstance(match_block, dict):
            match_criteria = match_block
        # Legacy flat format: treat as all_of
        if not match_criteria.get("any_of") and not match_criteria.get("all_of"):
            if match_criteria:
                match_criteria = {"all_of": [match_criteria]}

        rules = item.get("rules", {})
        if not isinstance(rules, dict):
            rules = {}

        results.append(ConventionRule(
            name=name,
            source=item.get("source", "discovered"),
            match_criteria=match_criteria,
            rules=rules,
            description=item.get("description", ""),
            compliance=float(item.get("compliance", 1.0)),
            last_checked=item.get("last_checked"),
        ))

    return results


def save_conventions(repo_root: str, conventions: List[ConventionRule]) -> str:
    """Write conventions to intent.yaml, preserving existing intents."""
    path = os.path.join(repo_root, "intent.yaml")

    # Preserve existing content before the conventions block
    existing = ""
    if os.path.exists(path):
        existing = read_repo_text(path).text

    # Strip any existing conventions block
    lines_out = []
    in_conventions = False
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped == "conventions:" or stripped.startswith("conventions:"):
            in_conventions = True
            continue
        if in_conventions:
            indent = len(line) - len(line.lstrip())
            if indent == 0 and stripped and not stripped.startswith("-"):
                in_conventions = False
            else:
                continue
        if not in_conventions:
            lines_out.append(line)

    # Remove trailing blank lines
    while lines_out and not lines_out[-1].strip():
        lines_out.pop()

    # Append conventions block
    if conventions:
        if lines_out:
            lines_out.append("")
        lines_out.append("conventions:")
        for conv in conventions:
            lines_out.append(f'  - name: "{conv.name}"')
            lines_out.append(f"    source: {conv.source}")
            if conv.match_criteria:
                lines_out.append("    match:")
                for key in ("any_of", "all_of"):
                    criteria_list = conv.match_criteria.get(key)
                    if criteria_list:
                        lines_out.append(f"      {key}:")
                        for criterion in criteria_list:
                            if isinstance(criterion, dict):
                                for ck, cv in criterion.items():
                                    if isinstance(cv, list):
                                        items = ", ".join(cv)
                                        lines_out.append(f"        - {ck}: [{items}]")
                                    else:
                                        lines_out.append(f'        - {ck}: "{cv}"')
            if conv.rules:
                lines_out.append("    rules:")
                for rk, rv in conv.rules.items():
                    if isinstance(rv, list):
                        items = ", ".join(str(v) for v in rv)
                        lines_out.append(f"      {rk}: [{items}]")
                    else:
                        lines_out.append(f"      {rk}: {rv}")
            if conv.description:
                lines_out.append(f'    description: "{conv.description}"')
            lines_out.append(f"    compliance: {conv.compliance}")
            if conv.last_checked:
                lines_out.append(f"    last_checked: {conv.last_checked}")

    content = "\n".join(lines_out) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _parse_conventions_list(text: str) -> List[dict]:
    """Parse the conventions list from intent.yaml.

    Handles nested structure:
        conventions:
          - name: "REST Controller"
            source: discovered
            match:
              any_of:
                - has_decorator: "@app.route"
              all_of:
                - not_imports: [sqlalchemy]
            rules:
              prohibited_imports: [sqlalchemy]
            description: "..."
            compliance: 1.0
    """
    items: List[dict] = []
    current: Optional[dict] = None
    in_conventions = False
    current_subkey = None  # "match", "rules"
    current_subsubkey = None  # "any_of", "all_of"
    current_list: Optional[list] = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "conventions:" or stripped.startswith("conventions:"):
            in_conventions = True
            continue

        if not in_conventions:
            continue

        indent = len(line) - len(line.lstrip())

        # New top-level key exits conventions block
        if indent == 0 and not stripped.startswith("-"):
            break

        # New convention item (indent 2, starts with "- ")
        if indent <= 2 and stripped.startswith("- "):
            if current is not None:
                items.append(current)
            current = {}
            current_subkey = None
            current_subsubkey = None
            current_list = None
            kv = stripped[2:].strip()
            if ":" in kv:
                k, v = kv.split(":", 1)
                current[k.strip()] = _parse_value(v.strip())
            continue

        if current is None:
            continue

        # Indent 4: top-level keys of current convention
        if indent == 4 and ":" in stripped and not stripped.startswith("-"):
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k in ("match", "rules"):
                current_subkey = k
                current_subsubkey = None
                current_list = None
                if v:
                    current[k] = _parse_value(v)
                else:
                    current.setdefault(k, {})
            else:
                current_subkey = None
                current_subsubkey = None
                current[k] = _parse_value(v)
            continue

        # Indent 6: sub-keys of match or rules
        if indent == 6 and current_subkey and ":" in stripped and not stripped.startswith("-"):
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            block = current.setdefault(current_subkey, {})
            if k in ("any_of", "all_of"):
                current_subsubkey = k
                if v:
                    block[k] = _parse_value(v)
                else:
                    block.setdefault(k, [])
                current_list = block.get(k)
            else:
                current_subsubkey = None
                current_list = None
                block[k] = _parse_value(v)
            continue

        # Indent 8: list items within any_of/all_of
        if indent == 8 and stripped.startswith("- ") and current_subsubkey:
            kv = stripped[2:].strip()
            if ":" in kv:
                k, v = kv.split(":", 1)
                criterion = {k.strip(): _parse_value(v.strip())}
                block = current.get(current_subkey, {})
                lst = block.setdefault(current_subsubkey, [])
                lst.append(criterion)
            continue

    if current is not None:
        items.append(current)

    return items


# ---------------------------------------------------------------------------
# Voice loading/saving
# ---------------------------------------------------------------------------

def load_voice_config(repo_root: str) -> Optional[dict]:
    """Load voice config from intent.yaml.

    Returns dict with mode, rules, stats, enforce, or None if no voice block.
    """
    path = os.path.join(repo_root, "intent.yaml")
    if not os.path.exists(path):
        return None

    text = read_repo_text(path).text

    return _parse_voice_block(text)


def save_voice_config(repo_root: str, voice) -> str:
    """Write voice config to intent.yaml, preserving intents and conventions."""
    path = os.path.join(repo_root, "intent.yaml")

    existing = ""
    if os.path.exists(path):
        existing = read_repo_text(path).text

    # Strip any existing voice block
    lines_out = []
    in_voice = False
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped == "voice:" or stripped.startswith("voice:"):
            in_voice = True
            continue
        if in_voice:
            indent_n = len(line) - len(line.lstrip())
            if indent_n == 0 and stripped and not stripped.startswith("-"):
                in_voice = False
            else:
                continue
        if not in_voice:
            lines_out.append(line)

    # Remove trailing blank lines
    while lines_out and not lines_out[-1].strip():
        lines_out.pop()

    # Append voice block
    if lines_out:
        lines_out.append("")
    lines_out.append("voice:")
    lines_out.append(f"  mode: {voice.mode}")

    if voice.rules:
        for key, val in voice.rules.items():
            lines_out.append(f"  {key}: |")
            for vline in val.strip().splitlines():
                lines_out.append(f"    {vline}")

    if voice.enforce:
        lines_out.append("  enforce:")
        for key, val in voice.enforce.items():
            if val is False:
                lines_out.append(f"    {key}: false")
            else:
                lines_out.append(f'    {key}: "{val}"')

    if voice.stats:
        lines_out.append("  stats:")
        for key, val in voice.stats.items():
            if val is None:
                lines_out.append(f"    {key}: null")
            elif isinstance(val, str):
                lines_out.append(f'    {key}: "{val}"')
            else:
                lines_out.append(f"    {key}: {val}")

    content = "\n".join(lines_out) + "\n"
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _parse_voice_block(text: str) -> Optional[dict]:
    """Parse the voice block from intent.yaml text."""
    in_voice = False
    result = {"mode": "adaptive", "rules": {}, "stats": {}, "enforce": {}}
    current_key = None
    current_section = None
    multiline_val = []

    for line in text.splitlines():
        stripped = line.strip()

        if stripped == "voice:" or stripped.startswith("voice:"):
            in_voice = True
            continue

        if not in_voice:
            continue

        indent_n = len(line) - len(line.lstrip())
        if indent_n == 0 and stripped and not stripped.startswith("-"):
            break

        if not stripped or stripped.startswith("#"):
            continue

        # Flush multiline value
        if indent_n == 4 and current_key and multiline_val and current_section == "rules":
            result["rules"][current_key] = "\n".join(multiline_val)
            current_key = None
            multiline_val = []

        # Indent 2: top-level voice keys
        if indent_n == 2 and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()

            if key == "mode":
                result["mode"] = val.strip('"').strip("'")
            elif key == "enforce":
                current_section = "enforce"
                current_key = None
            elif key == "stats":
                current_section = "stats"
                current_key = None
            elif val == "|":
                current_section = "rules"
                current_key = key
                multiline_val = []
            elif val:
                result["rules"][key] = val.strip('"').strip("'")
                current_section = "rules"
                current_key = None
            continue

        # Indent 4: enforce/stats values or multiline continuation
        if indent_n == 4 and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")

            if current_section == "enforce":
                if val == "false":
                    result["enforce"][key] = False
                else:
                    result["enforce"][key] = val
            elif current_section == "stats":
                if val == "null":
                    result["stats"][key] = None
                else:
                    try:
                        result["stats"][key] = float(val)
                    except ValueError:
                        result["stats"][key] = val
            continue

        # Multiline rule continuation
        if indent_n >= 4 and current_key and current_section == "rules":
            multiline_val.append(stripped)
            continue

    # Flush final multiline value
    if current_key and multiline_val and current_section == "rules":
        result["rules"][current_key] = "\n".join(multiline_val)

    if not in_voice:
        return None

    return result
