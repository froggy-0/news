from __future__ import annotations

from email.utils import parsedate_to_datetime
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import requests

from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    policy_for,
    record_failure,
    record_request,
    record_retry,
    record_skip,
    record_success,
    wait_for_provider_slot,
)

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

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider: str | None = None,
        retryable: bool = False,
        rate_limited: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.retryable = retryable
        self.rate_limited = rate_limited

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
    provider: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> requests.Response:
    if not is_host_resolvable(url):
        raise HttpFetchError(f"호스트 주소를 확인할 수 없어요: {urlparse(url).hostname}")

    unavailable_reason = disabled_reason(provider)
    if unavailable_reason:
        record_skip(provider)
        raise HttpFetchError(
            f"{provider} 제공자는 이번 실행에서 더 이상 쓰지 않을게요: {unavailable_reason}",
            provider=provider,
        )

    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        wait_for_provider_slot(provider)
        record_request(provider)
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
            )
            if response.status_code < 400:
                record_success(provider)
                return response

            should_retry = _is_retryable_status(response.status_code, provider=provider)
            error = HttpFetchError(
                f"HTTP {response.status_code} 응답을 받았어요: {url}",
                status_code=response.status_code,
                provider=provider,
                retryable=should_retry,
                rate_limited=response.status_code == 429,
            )
            if not should_retry or attempt == retries:
                record_failure(provider)
                raise error

            record_retry(provider)
            logger.warning(
                "HTTP 요청을 다시 시도하는 중이에요 (%s/%s). 대상=%s | status=%s",
                attempt,
                retries,
                url,
                response.status_code,
            )
            time.sleep(
                _retry_delay_seconds(
                    response=response,
                    attempt=attempt,
                    backoff_seconds=backoff_seconds,
                    provider=provider,
                )
            )
            continue
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries:
                record_failure(provider)
                break
            record_retry(provider)
            logger.warning(
                "HTTP 요청을 다시 시도하는 중이에요 (%s/%s). 대상=%s | %s",
                attempt,
                retries,
                url,
                exc,
            )
            time.sleep(backoff_seconds * attempt)

    raise HttpFetchError(
        f"URL을 가져오지 못했어요: {url}",
        provider=provider,
        retryable=True,
    ) from last_error


def _is_retryable_status(status_code: int, *, provider: str | None) -> bool:
    return status_code in policy_for(provider).retryable_statuses


def _retry_delay_seconds(
    *,
    response: requests.Response,
    attempt: int,
    backoff_seconds: float,
    provider: str | None,
) -> float:
    retry_after = response.headers.get("Retry-After", "").strip()
    if retry_after and policy_for(provider).respect_retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                delay = retry_at.timestamp() - time.time()
                return max(delay, 0.0)
            except (TypeError, ValueError, OverflowError):
                pass
    return backoff_seconds * attempt



def get_json_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    provider: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> dict[str, Any]:
    response = _request_with_retry(
        url,
        params=params,
        headers=headers,
        provider=provider,
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
    provider: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> str:
    response = _request_with_retry(
        url,
        params=params,
        headers=headers,
        provider=provider,
        timeout=timeout,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )
    return response.text
