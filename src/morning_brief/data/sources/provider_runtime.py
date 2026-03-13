from __future__ import annotations

import time
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderPolicy:
    name: str
    min_interval_seconds: float = 0.0
    retryable_statuses: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})
    respect_retry_after: bool = True


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
    "alpha_vantage": ProviderPolicy(name="alpha_vantage", min_interval_seconds=1.05),
    "coingecko": ProviderPolicy(name="coingecko", min_interval_seconds=0.2),
    "fred": ProviderPolicy(name="fred", min_interval_seconds=0.1),
    "gdelt": ProviderPolicy(name="gdelt", min_interval_seconds=0.4),
    "btc_etf_official": ProviderPolicy(name="btc_etf_official", min_interval_seconds=0.2),
    "perplexity": ProviderPolicy(name="perplexity", min_interval_seconds=0.2),
    "grok": ProviderPolicy(name="grok", min_interval_seconds=0.2),
}

_provider_last_request_at: dict[str, float] = {}
_provider_disabled_reasons: dict[str, str] = {}
_provider_stats: dict[str, ProviderStats] = {}


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
