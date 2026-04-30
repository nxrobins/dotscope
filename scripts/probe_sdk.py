"""Live probe of claude-agent-sdk against orchestrator adapter assumptions.

Run with: python scripts/probe_sdk.py
"""

from __future__ import annotations

import dataclasses
import inspect
import sys

import claude_agent_sdk as sdk


def main() -> int:
    print("=== claude-agent-sdk probe ===")
    print(f"version: {getattr(sdk, '__version__', 'unknown')}")
    print(f"public names: {sorted(n for n in dir(sdk) if not n.startswith('_'))}")
    print()

    failures: list[str] = []

    # --- ClaudeAgentOptions
    print("--- ClaudeAgentOptions ---")
    opts_cls = sdk.ClaudeAgentOptions
    is_dc = dataclasses.is_dataclass(opts_cls)
    print(f"is dataclass: {is_dc}")
    if not is_dc:
        failures.append("ClaudeAgentOptions is not a dataclass — adapter assumes kwargs.")
        fields = {}
    else:
        fields = {f.name: f for f in dataclasses.fields(opts_cls)}
    print(f"all fields: {sorted(fields)}")
    print()

    expected_keys = [
        "mcp_servers", "setting_sources", "cwd", "model",
        "permission_mode", "allowed_tools", "max_turns", "system_prompt",
    ]
    for key in expected_keys:
        if key in fields:
            f = fields[key]
            try:
                default_repr = (
                    "<MISSING>" if f.default is dataclasses.MISSING and
                    f.default_factory is dataclasses.MISSING
                    else (
                        f.default if f.default is not dataclasses.MISSING
                        else f.default_factory()
                    )
                )
            except Exception:
                default_repr = "<unrepresentable>"
            print(f"  {key}: type={f.type}  default={default_repr!r}")
        else:
            print(f"  {key}: ABSENT")
            failures.append(f"ClaudeAgentOptions.{key} field is absent.")
    print()

    # --- Construct options like build_sdk_options does
    print("--- Constructing options exactly like build_sdk_options ---")
    constructed_ok = False
    try:
        o = sdk.ClaudeAgentOptions(
            cwd=".",
            mcp_servers={"dotscope": {"type": "stdio", "command": "dotscope-mcp"}},
            setting_sources=["local"],
            model="claude-opus-4-7",
            permission_mode="bypassPermissions",
        )
        constructed_ok = True
        print(f"  OK: {type(o).__name__}")
        print(f"  mcp_servers: {getattr(o, 'mcp_servers', '<missing attr>')}")
        print(f"  setting_sources: {getattr(o, 'setting_sources', '<missing attr>')}")
        print(f"  model: {getattr(o, 'model', '<missing attr>')}")
    except TypeError as exc:
        failures.append(f"ClaudeAgentOptions construction TypeError: {exc}")
        print(f"  FAIL: {type(exc).__name__}: {exc}")
    except Exception as exc:
        failures.append(f"ClaudeAgentOptions construction error: {type(exc).__name__}: {exc}")
        print(f"  FAIL: {type(exc).__name__}: {exc}")

    # Try with empty mcp_servers (baseline arm shape)
    if constructed_ok:
        try:
            sdk.ClaudeAgentOptions(
                cwd=".",
                mcp_servers={},
                setting_sources=["local"],
                model="claude-opus-4-7",
                permission_mode="bypassPermissions",
            )
            print("  baseline shape (mcp_servers={}) accepted")
        except Exception as exc:
            failures.append(f"baseline ClaudeAgentOptions construction error: {exc}")
            print(f"  baseline shape FAIL: {exc}")
    print()

    # --- AssistantMessage
    print("--- AssistantMessage ---")
    am_cls = sdk.AssistantMessage
    am_is_dc = dataclasses.is_dataclass(am_cls)
    print(f"is dataclass: {am_is_dc}")
    am_fields = (
        {f.name: f for f in dataclasses.fields(am_cls)} if am_is_dc else {}
    )
    print(f"all fields: {sorted(am_fields)}")
    expected_am = ["content", "model", "usage", "message_id"]
    for key in expected_am:
        present = key in am_fields
        print(f"  {key}: {'present' if present else 'ABSENT'}")
        if not present:
            failures.append(f"AssistantMessage.{key} field is absent.")
    print()

    # --- query() signature
    print("--- query() signature ---")
    try:
        sig = inspect.signature(sdk.query)
        print(f"signature: {sig}")
    except (TypeError, ValueError) as exc:
        print(f"signature inspection failed: {exc}")
    print()

    # --- Auxiliary types the adapter uses
    print("--- Adjacent types the adapter touches ---")
    for name in ["SystemMessage", "TextBlock", "ResultMessage"]:
        cls = getattr(sdk, name, None)
        print(f"  {name}: {'present' if cls is not None else 'ABSENT'}")
        if cls is None:
            failures.append(f"sdk.{name} is absent — adapter imports it.")
    print()

    # --- Try the orchestrator's load_real_sdk_adapter
    print("--- Orchestrator load_real_sdk_adapter ---")
    try:
        from dotscope.orchestrator import load_real_sdk_adapter
        adapter = load_real_sdk_adapter()
        keys = sorted(adapter)
        print(f"  loaded keys: {keys}")
        if "sdk_query" not in adapter:
            failures.append("adapter missing sdk_query")
    except Exception as exc:
        failures.append(f"load_real_sdk_adapter error: {type(exc).__name__}: {exc}")
        print(f"  FAIL: {type(exc).__name__}: {exc}")
    print()

    # --- Summary
    print("=== probe summary ===")
    if failures:
        print(f"FAILURES: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
