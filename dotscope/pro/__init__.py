"""Dotscope Pro integration — remote structural intelligence.

This package ships with the OSS repo. It defines the ``ProProvider`` interface
and a discovery helper, but holds NO swarm data itself. A running Pro backend
is reached over HTTP by the ``RemoteProProvider`` in ``.remote``. When no Pro
credentials are configured, ``get_provider()`` returns ``None`` and all
enrichment sites downstream become silent no-ops — OSS users see zero
degradation, no nags, no errors.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import (
        Directive,
        FailureDensity,
        GlobalBaseline,
        StructuralReport,
    )


class ProProvider(ABC):
    """Abstract interface for Pro intelligence.

    The OSS repo defines the shape; the Pro backend fills it. Every method
    must be fail-open — callers should never need to wrap calls in try/except
    to defend against network or backend failures.
    """

    @abstractmethod
    def compare_topology(self, local_graph: dict) -> "StructuralReport":
        """Compare anonymized local topology against the Genesis swarm."""
        ...

    @abstractmethod
    def get_failure_density(self, loc_count: int, in_degree: int) -> "FailureDensity":
        """Query historical failure correlation for a given file shape."""
        ...

    @abstractmethod
    def get_global_npmi_baseline(self) -> "GlobalBaseline":
        """Retrieve the global average NPMI coupling baseline."""
        ...

    @abstractmethod
    def get_directives(self, fingerprint: dict, topology: dict) -> "List[Directive]":
        """Request architectural directives for the local structure."""
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """Cheap health probe. Must NOT retry; should return quickly."""
        ...


def _credentials_path() -> Path:
    return Path.home() / ".dotscope" / "credentials"


def _load_credentials_file() -> Optional[tuple]:
    """Return ``(url, token)`` from ``~/.dotscope/credentials`` or ``None``.

    Fails silently — any IOError, JSONDecodeError, or missing keys yield
    ``None``. We never raise out of discovery.
    """
    path = _credentials_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            creds = json.load(f)
    except Exception:
        return None
    if not isinstance(creds, dict):
        return None
    url = creds.get("pro_url")
    token = creds.get("token")
    if isinstance(url, str) and isinstance(token, str) and url and token:
        return url, token
    return None


def get_provider() -> Optional[ProProvider]:
    """Auto-discover Pro availability.

    Discovery order:
      1. ``DOTSCOPE_PRO_URL`` + ``DOTSCOPE_PRO_TOKEN`` environment variables.
      2. ``~/.dotscope/credentials`` JSON with ``pro_url`` and ``token`` keys.
      3. ``None`` (OSS mode — no Pro, no errors, no nag).
    """
    pro_url = os.environ.get("DOTSCOPE_PRO_URL")
    pro_token = os.environ.get("DOTSCOPE_PRO_TOKEN")
    if pro_url and pro_token:
        from .remote import RemoteProProvider
        return RemoteProProvider(pro_url, pro_token)

    creds = _load_credentials_file()
    if creds is not None:
        from .remote import RemoteProProvider
        return RemoteProProvider(creds[0], creds[1])

    return None


__all__ = ["ProProvider", "get_provider"]
