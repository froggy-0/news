from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, TypeVar


@dataclass(frozen=True)
class ProviderPolicy:
    name: str
    min_interval_seconds: float = 0.0
    retryable_statuses: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})
    respect_retry_after: bool = True
    max_attempts: int = 3
    base_backoff_seconds: float = 1.2
    max_backoff_seconds: float = 12.0
    jitter_ratio: float = 0.2


@dataclass
class ProviderStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    skips: int = 0
    circuit_opened: int = 0


DEFAULT_POLICY = ProviderPolicy(name="default")
PROVIDER_POLICIES = {
    "coingecko": ProviderPolicy(name="coingecko", min_interval_seconds=0.25),
    "fred": ProviderPolicy(name="fred", min_interval_seconds=0.1, base_backoff_seconds=1.0),
    "btc_etf_official": ProviderPolicy(
        name="btc_etf_official",
        min_interval_seconds=0.25,
        base_backoff_seconds=1.0,
    ),
    "perplexity": ProviderPolicy(
        name="perplexity",
        min_interval_seconds=0.5,
        base_backoff_seconds=1.5,
        max_backoff_seconds=10.0,
    ),
    "grok_official": ProviderPolicy(
        name="grok_official",
        min_interval_seconds=0.5,
        base_backoff_seconds=1.5,
        max_backoff_seconds=10.0,
    ),
    "grok_keyword": ProviderPolicy(
        name="grok_keyword",
        min_interval_seconds=0.5,
        base_backoff_seconds=1.5,
        max_backoff_seconds=10.0,
    ),
    "grok_web_search": ProviderPolicy(
        name="grok_web_search",
        min_interval_seconds=0.5,
        base_backoff_seconds=1.5,
        max_backoff_seconds=10.0,
    ),
    "gemini": ProviderPolicy(
        name="gemini",
        min_interval_seconds=0.5,
        base_backoff_seconds=1.5,
        max_backoff_seconds=10.0,
    ),
    "kis": ProviderPolicy(
        name="kis",
        min_interval_seconds=0.4,
        retryable_statuses=frozenset({408, 429, 500, 502, 503, 504}),
        max_attempts=5,
        base_backoff_seconds=1.0,
        max_backoff_seconds=8.0,
    ),
    "newsapi": ProviderPolicy(name="newsapi", min_interval_seconds=0.35, base_backoff_seconds=1.0),
    "coindesk": ProviderPolicy(
        name="coindesk",
        min_interval_seconds=0.35,
        base_backoff_seconds=1.0,
        max_backoff_seconds=8.0,
    ),
    "yfinance": ProviderPolicy(
        name="yfinance", min_interval_seconds=0.35, base_backoff_seconds=1.0
    ),
    "alternative_me": ProviderPolicy(
        name="alternative_me",
        min_interval_seconds=0.35,
        base_backoff_seconds=1.0,
    ),
    "binance_spot": ProviderPolicy(
        name="binance_spot",
        min_interval_seconds=0.1,
        retryable_statuses=frozenset({429, 500, 502, 503, 504}),
        base_backoff_seconds=1.2,
        max_attempts=3,
    ),
    "binance_futures": ProviderPolicy(
        name="binance_futures",
        min_interval_seconds=0.1,
        retryable_statuses=frozenset({429, 500, 502, 503, 504}),
        base_backoff_seconds=1.2,
        max_attempts=3,
    ),
    "bybit": ProviderPolicy(
        name="bybit",
        min_interval_seconds=0.1,
        retryable_statuses=frozenset({429, 500, 502, 503, 504}),
        base_backoff_seconds=1.2,
        max_attempts=3,
    ),
}

_provider_last_request_at: dict[str, float] = {}
_provider_disabled_reasons: dict[str, str] = {}
_provider_stats: dict[str, ProviderStats] = {}
_T = TypeVar("_T")


def reset_provider_runtime_state() -> None:
    _provider_last_request_at.clear()
    _provider_disabled_reasons.clear()
    _provider_stats.clear()


def policy_for(provider: str | None) -> ProviderPolicy:
    if not provider:
        return DEFAULT_POLICY
    return PROVIDER_POLICIES.get(provider, ProviderPolicy(name=provider))


def disabled_reason(provider: str | None) -> str | None:
    if not provider:
        return None
    return _provider_disabled_reasons.get(provider)


def open_circuit(provider: str, reason: str) -> None:
    if provider not in _provider_disabled_reasons:
        _provider_disabled_reasons[provider] = reason
        record_circuit_opened(provider)


def wait_for_provider_slot(provider: str | None) -> None:
    if not provider:
        return

    policy = policy_for(provider)
    if policy.min_interval_seconds <= 0:
        _provider_last_request_at[provider] = time.monotonic()
        return

    now = time.monotonic()
    previous = _provider_last_request_at.get(provider)
    if previous is not None:
        remaining = policy.min_interval_seconds - (now - previous)
        if remaining > 0:
            time.sleep(remaining)
    _provider_last_request_at[provider] = time.monotonic()


def _stats_for(provider: str | None) -> ProviderStats:
    key = provider or "default"
    if key not in _provider_stats:
        _provider_stats[key] = ProviderStats()
    return _provider_stats[key]


def record_request(provider: str | None) -> None:
    _stats_for(provider).requests += 1


def record_success(provider: str | None) -> None:
    _stats_for(provider).successes += 1


def record_failure(provider: str | None) -> None:
    _stats_for(provider).failures += 1


def record_retry(provider: str | None) -> None:
    _stats_for(provider).retries += 1


def record_skip(provider: str | None) -> None:
    _stats_for(provider).skips += 1


def record_circuit_opened(provider: str | None) -> None:
    _stats_for(provider).circuit_opened += 1


def provider_stats_snapshot() -> dict[str, dict[str, int]]:
    return {provider: asdict(stats) for provider, stats in sorted(_provider_stats.items())}


def parse_retry_after_seconds(value: object) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        return max(float(raw), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None

    delay = retry_at.timestamp() - time.time()
    return max(delay, 0.0)


def retry_delay_seconds(
    *,
    provider: str | None,
    attempt: int,
    retry_after_seconds: float | None = None,
    base_backoff_seconds: float | None = None,
) -> float:
    policy = policy_for(provider)
    if retry_after_seconds is not None and policy.respect_retry_after:
        return retry_after_seconds

    base_delay = base_backoff_seconds or policy.base_backoff_seconds
    capped_delay = min(policy.max_backoff_seconds, base_delay * (2 ** max(attempt - 1, 0)))
    if policy.jitter_ratio <= 0:
        return capped_delay

    jitter_span = capped_delay * policy.jitter_ratio
    return max(capped_delay - jitter_span + (random.random() * jitter_span * 2), 0.0)


def execute_with_provider_retry(
    *,
    provider: str | None,
    operation: Callable[[], _T],
    should_retry: Callable[[Exception], bool],
    on_retry: Callable[[Exception, int, int, float], None] | None = None,
    max_attempts: int | None = None,
    base_backoff_seconds: float | None = None,
    retry_after_seconds_for_error: Callable[[Exception], float | None] | None = None,
) -> _T:
    attempts = max(max_attempts or policy_for(provider).max_attempts, 1)

    for attempt in range(1, attempts + 1):
        wait_for_provider_slot(provider)
        record_request(provider)
        try:
            result = operation()
        except Exception as exc:
            if attempt == attempts or not should_retry(exc):
                record_failure(provider)
                raise

            record_retry(provider)
            retry_after_seconds = None
            if retry_after_seconds_for_error is not None:
                retry_after_seconds = retry_after_seconds_for_error(exc)
            delay = retry_delay_seconds(
                provider=provider,
                attempt=attempt,
                retry_after_seconds=retry_after_seconds,
                base_backoff_seconds=base_backoff_seconds,
            )
            if on_retry is not None:
                on_retry(exc, attempt, attempts, delay)
            time.sleep(delay)
            continue

        record_success(provider)
        return result

    raise RuntimeError("provider retry loop terminated unexpectedly")
