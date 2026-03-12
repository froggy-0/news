from __future__ import annotations

import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1.2
DEFAULT_HEADERS = {
    "User-Agent": "morning-market-brief/1.0",
    "Accept": "application/json,text/plain,*/*",
}


class HttpFetchError(RuntimeError):
    """Raised when an HTTP fetch fails after retries."""

_host_resolution_cache: dict[str, bool] = {}


def _is_host_resolvable(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return True

    cached = _host_resolution_cache.get(host)
    if cached is not None:
        return cached

    try:
        socket.gethostbyname(host)
        _host_resolution_cache[host] = True
    except socket.gaierror:
        _host_resolution_cache[host] = False
        logger.warning("DNS resolution failed for host: %s", host)

    return _host_resolution_cache[host]



def _request_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> requests.Response:
    if not _is_host_resolvable(url):
        raise HttpFetchError(f"Host is not resolvable: {urlparse(url).hostname}")

    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries:
                break
            logger.warning(
                "HTTP retry %s/%s failed for %s: %s",
                attempt,
                retries,
                url,
                exc,
            )
            time.sleep(backoff_seconds * attempt)

    raise HttpFetchError(f"Failed to fetch URL: {url}") from last_error



def get_json_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> dict[str, Any]:
    response = _request_with_retry(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HttpFetchError(f"Invalid JSON response from {url}") from exc

    if not isinstance(payload, dict):
        raise HttpFetchError(f"Unexpected JSON shape for {url}")

    return payload



def get_text_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> str:
    response = _request_with_retry(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )
    return response.text
