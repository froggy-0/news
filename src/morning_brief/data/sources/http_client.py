from __future__ import annotations

import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import requests

from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    execute_with_provider_retry,
    parse_retry_after_seconds,
    policy_for,
    record_skip,
)
from morning_brief.logging_utils import log_structured

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
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.retryable = retryable
        self.rate_limited = rate_limited
        self.retry_after_seconds = retry_after_seconds


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
        log_structured(
            logger,
            event="error.raised",
            message="호스트 주소를 확인하지 못했어요.",
            level=logging.WARNING,
            provider="http",
            reason=host,
        )

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

    def perform_request() -> requests.Response:
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise HttpFetchError(
                f"URL을 가져오는 중 연결 문제가 있었어요: {url}",
                provider=provider,
                retryable=True,
            ) from exc

        if response.status_code < 400:
            return response

        raise HttpFetchError(
            f"HTTP {response.status_code} 응답을 받았어요: {url}",
            status_code=response.status_code,
            provider=provider,
            retryable=_is_retryable_status(response.status_code, provider=provider),
            rate_limited=response.status_code == 429,
            retry_after_seconds=parse_retry_after_seconds(response.headers.get("Retry-After")),
        )

    def log_retry(exc: Exception, attempt: int, max_attempts: int, delay: float) -> None:
        if isinstance(exc, HttpFetchError) and exc.status_code is not None:
            log_structured(
                logger,
                event="provider.retry",
                message="HTTP 요청을 다시 시도하는 중이에요.",
                level=logging.WARNING,
                provider=provider or "http",
                attempt=attempt,
                max_attempts=max_attempts,
                url=url,
                status=exc.status_code,
                retryable=True,
                delay_seconds=delay,
            )
            return

        log_structured(
            logger,
            event="provider.retry",
            message="HTTP 요청을 다시 시도하는 중이에요.",
            level=logging.WARNING,
            provider=provider or "http",
            attempt=attempt,
            max_attempts=max_attempts,
            url=url,
            reason=str(exc),
            retryable=True,
            delay_seconds=delay,
        )

    return execute_with_provider_retry(
        provider=provider,
        operation=perform_request,
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=log_retry,
        max_attempts=retries,
        base_backoff_seconds=backoff_seconds,
        retry_after_seconds_for_error=lambda exc: exc.retry_after_seconds
        if isinstance(exc, HttpFetchError)
        else None,
    )


def _is_retryable_status(status_code: int, *, provider: str | None) -> bool:
    return status_code in policy_for(provider).retryable_statuses


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
