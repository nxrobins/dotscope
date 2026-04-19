"""Helpers for explicit backward-compatibility shim modules."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


_LOCAL_MODULE_ATTRS = frozenset({
    "__all__",
    "__annotations__",
    "__builtins__",
    "__cached__",
    "__class__",
    "__dict__",
    "__doc__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__path__",
    "__spec__",
    "__weakref__",
    "_TARGET_MODULE",
})


class _CompatModule(ModuleType):
    """Proxy shim attributes into the canonical target module."""

    def __getattribute__(self, name: str):
        if name in _LOCAL_MODULE_ATTRS:
            return super().__getattribute__(name)

        target_module = super().__getattribute__("_TARGET_MODULE")
        try:
            return getattr(target_module, name)
        except AttributeError:
            return super().__getattribute__(name)

    def __dir__(self):
        target_module = super().__getattribute__("_TARGET_MODULE")
        return sorted(set(super().__dir__()) | set(dir(target_module)))

    def __setattr__(self, name: str, value):
        if name in _LOCAL_MODULE_ATTRS:
            super().__setattr__(name, value)
            return

        target_module = super().__getattribute__("_TARGET_MODULE")
        setattr(target_module, name, value)

    def __delattr__(self, name: str):
        if name in _LOCAL_MODULE_ATTRS:
            super().__delattr__(name)
            return

        target_module = super().__getattribute__("_TARGET_MODULE")
        delattr(target_module, name)


def install_compat_shim(module_name: str, target_name: str) -> None:
    """Configure the active module as a write-through shim to a target module."""
    package_name = module_name.rsplit(".", 1)[0]
    target_module = importlib.import_module(target_name, package=package_name)
    module = sys.modules[module_name]

    public_names = getattr(target_module, "__all__", None)
    if public_names is None:
        public_names = [name for name in vars(target_module) if not name.startswith("_")]

    module.__dict__["_TARGET_MODULE"] = target_module
    module.__dict__["__all__"] = list(public_names)
    module.__class__ = _CompatModule
