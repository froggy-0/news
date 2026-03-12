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
HOST_RESOLUTION_CACHE_TTL_SECONDS = 300.0
DEFAULT_HEADERS = {
    "User-Agent": "morning-market-brief/1.0",
    "Accept": "application/json,text/plain,*/*",
}


class HttpFetchError(RuntimeError):
    """Raised when an HTTP fetch fails after retries."""

_host_resolution_cache: dict[str, tuple[bool, float]] = {}


def _normalize_host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").strip().lower()


def is_host_resolvable(value: str) -> bool:
    host = _normalize_host(value)
    if not host:
        return True

    now = time.monotonic()
    cached = _host_resolution_cache.get(host)
    if cached is not None:
        is_resolvable, cached_at = cached
        if now - cached_at < HOST_RESOLUTION_CACHE_TTL_SECONDS:
            return is_resolvable

    try:
        socket.gethostbyname(host)
        _host_resolution_cache[host] = (True, now)
    except socket.gaierror:
        _host_resolution_cache[host] = (False, now)
        logger.warning("호스트 주소를 확인하지 못했어요: %s", host)

    return _host_resolution_cache[host][0]



def _request_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> requests.Response:
    if not is_host_resolvable(url):
        raise HttpFetchError(f"호스트 주소를 확인할 수 없어요: {urlparse(url).hostname}")

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
                "HTTP 요청을 다시 시도하는 중이에요 (%s/%s). 대상=%s | %s",
                attempt,
                retries,
                url,
                exc,
            )
            time.sleep(backoff_seconds * attempt)

    raise HttpFetchError(f"URL을 가져오지 못했어요: {url}") from last_error



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
        raise HttpFetchError(f"JSON 응답 형식을 확인하지 못했어요: {url}") from exc

    if not isinstance(payload, dict):
        raise HttpFetchError(f"JSON 응답 구조가 예상과 달라요: {url}")

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
