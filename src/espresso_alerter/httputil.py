"""Shared HTTP helper: timeouts + retries with exponential backoff."""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(15.0)


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff_base: float = 1.5,
    **kwargs,
) -> httpx.Response:
    """Issue a request, retrying transient failures (network errors, 5xx, 429).

    Raises the last exception if all attempts fail — callers catch and treat
    the source as down for this sweep.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.request(method, url, timeout=TIMEOUT, **kwargs)
            if resp.status_code in (429,) or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"retryable status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            wait = backoff_base * (2**attempt)
            log.warning(
                "http retry attempt=%d/%d url=%s error=%s wait=%.1fs",
                attempt + 1, retries, url, exc, wait,
            )
            if attempt < retries - 1:
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc
