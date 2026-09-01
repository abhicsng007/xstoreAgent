"""Small retry helper for Vertex AI calls that can hit transient quota limits.

New GCP projects have modest Gemini/embedding quota, so rapid sequential ingestion
can trip 429 RESOURCE_EXHAUSTED. This retries such transient errors with
exponential backoff so ingestion (and a live demo) stays smooth.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

_TRANSIENT = ("429", "resource_exhausted", "rate limit", "503", "unavailable", "deadline")


def is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(tok in msg for tok in _TRANSIENT)


def with_retry(fn: Callable[[], T], attempts: int = 4, base_delay: float = 2.0) -> T:
    """Call `fn`, retrying transient (quota/rate) errors with exponential backoff.

    Non-transient errors are raised immediately. The last transient error is
    re-raised after the final attempt.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we classify below
            if not is_transient(exc):
                raise
            last = exc
            if i < attempts - 1:
                time.sleep(base_delay * (2**i))
    assert last is not None
    raise last
