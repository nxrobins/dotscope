"""HTTP client for the Dotscope Pro API.

All Pro data is held in memory for the duration of a single call — nothing
is ever written to disk from this module. Every public method is fail-open:
on timeout, network error, or bad response it returns a defaulted model
instance so callers never need a try/except.

Retry policy
------------
Transient failures (timeouts, socket errors, HTTP 5xx) are retried up to
``_MAX_ATTEMPTS`` times with exponential backoff and ±25% jitter.
Non-transient failures (HTTP 4xx, JSON decode errors) are NOT retried — they
won't get better with time. ``is_healthy()`` skips retries entirely so
``dotscope pro status`` feels snappy when the backend is offline.
"""

from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from . import ProProvider
from .models import (
    Directive,
    FailureDensity,
    GlobalBaseline,
    StructuralReport,
)

_MAX_ATTEMPTS = 3
_BASE_BACKOFF = 0.25  # seconds
_DEFAULT_TIMEOUT = 3.0
_HEALTH_TIMEOUT = 1.0


class _TransientError(Exception):
    """Marker exception so retry logic can distinguish transient vs. fatal."""


def _is_transient_http(err: urllib.error.HTTPError) -> bool:
    """HTTP 5xx is transient; 4xx (auth, bad request) is not."""
    return 500 <= err.code < 600


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with ±25% jitter: 0.25s, 0.75s, 2.25s ...

    ``attempt`` is 0-indexed (delay before the *next* attempt).
    """
    base = _BASE_BACKOFF * (3 ** attempt)
    jitter = base * 0.25
    return max(0.0, base + random.uniform(-jitter, jitter))


class RemoteProProvider(ProProvider):
    """Remote HTTP implementation of :class:`ProProvider`."""

    def __init__(self, base_url: str, token: str, timeout: float = _DEFAULT_TIMEOUT):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    # -- Transport -------------------------------------------------------

    def _open(self, req: urllib.request.Request, timeout: float) -> Dict[str, Any]:
        """Open ``req`` and return the decoded JSON body.

        Raises :class:`_TransientError` for retryable failures and other
        exceptions (``urllib.error.HTTPError`` for 4xx, ``json.JSONDecodeError``)
        for fatal ones.
        """
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if _is_transient_http(e):
                raise _TransientError(str(e)) from e
            raise  # 4xx — fatal, do not retry
        except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as e:
            raise _TransientError(str(e)) from e

        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # Server returned garbage — not retryable.
            return {}

    def _request_with_retry(
        self,
        build_request: Callable[[], urllib.request.Request],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Issue a request with retry on transient failures.

        Returns ``{}`` on permanent failure so the public methods can always
        produce a defaulted model instance.
        """
        t = timeout if timeout is not None else self._timeout
        last_error: Optional[Exception] = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._open(build_request(), t)
            except _TransientError as e:
                last_error = e
                if attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(_backoff_delay(attempt))
                    continue
            except Exception as e:
                # Non-transient (HTTP 4xx, value errors, etc.) — give up fast.
                last_error = e
                break
        _ = last_error  # retained for debugging; never re-raised (fail-open)
        return {}

    def _build_post(self, endpoint: str, payload: dict) -> urllib.request.Request:
        data = json.dumps(payload).encode("utf-8")
        return urllib.request.Request(
            f"{self._base_url}{endpoint}",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
        )

    def _build_get(self, endpoint: str) -> urllib.request.Request:
        return urllib.request.Request(
            f"{self._base_url}{endpoint}",
            method="GET",
            headers={"Authorization": f"Bearer {self._token}"},
        )

    # -- ProProvider API -------------------------------------------------

    def compare_topology(self, local_graph: dict) -> StructuralReport:
        raw = self._request_with_retry(
            lambda: self._build_post("/api/v1/pro/compare", {"graph_topology": local_graph})
        )
        if not raw:
            return StructuralReport()
        return StructuralReport.from_dict(raw)

    def get_failure_density(self, loc_count: int, in_degree: int) -> FailureDensity:
        raw = self._request_with_retry(
            lambda: self._build_post(
                "/api/v1/pro/failure-density",
                {"loc_count": loc_count, "in_degree": in_degree},
            )
        )
        if not raw:
            return FailureDensity(
                density=0.0,
                severity="unknown",
                matched_repos=0,
                explanation="Pro unavailable",
            )
        return FailureDensity.from_dict(raw)

    def get_global_npmi_baseline(self) -> GlobalBaseline:
        raw = self._request_with_retry(lambda: self._build_get("/api/v1/pro/npmi-baseline"))
        if not raw:
            return GlobalBaseline()
        return GlobalBaseline.from_dict(raw)

    def get_directives(self, fingerprint: dict, topology: dict) -> List[Directive]:
        raw = self._request_with_retry(
            lambda: self._build_post(
                "/api/v1/pro/directives",
                {"fingerprint": fingerprint, "graph_topology": topology},
            )
        )
        # Directives endpoint may return either a bare list or {"directives": [...]}
        items: List[dict] = []
        if isinstance(raw, list):
            items = [d for d in raw if isinstance(d, dict)]
        elif isinstance(raw, dict):
            maybe = raw.get("directives")
            if isinstance(maybe, list):
                items = [d for d in maybe if isinstance(d, dict)]
        return [Directive.from_dict(d) for d in items]

    def is_healthy(self) -> bool:
        """Single-shot health probe. Does NOT retry."""
        try:
            raw = self._open(self._build_get("/api/v1/pro/health"), _HEALTH_TIMEOUT)
        except Exception:
            return False
        return isinstance(raw, dict) and raw.get("status") == "ok"
