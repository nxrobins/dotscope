"""Ephemeral in-memory cache for Pro responses within a single process.

This module NEVER touches the filesystem. Values live in a module-level dict
with a 5-minute TTL and vanish when the Python process exits. Tests assert
that this file contains zero filesystem operations — do not add ``open``,
``Path``, ``json.dump``, ``pickle``, or any other persistence here.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

_TTL_SECONDS = 300  # one coding session
_SESSION_CACHE: Dict[str, Tuple[float, Any]] = {}


def cache_get(key: str) -> Any:
    """Return the cached value for ``key``, or ``None`` if missing/expired."""
    entry = _SESSION_CACHE.get(key)
    if entry is None:
        return None
    timestamp, value = entry
    if time.time() - timestamp > _TTL_SECONDS:
        _SESSION_CACHE.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any) -> None:
    """Store ``value`` under ``key`` with the current timestamp."""
    _SESSION_CACHE[key] = (time.time(), value)


def cache_clear() -> None:
    """Drop every cached entry. Useful for tests and for ``pro logout``."""
    _SESSION_CACHE.clear()
