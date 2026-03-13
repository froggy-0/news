"""Deprecated adapter kept only for reference.

Alpha Vantage free-tier collection is disabled in the production pipeline due
to quota instability. Do not re-enable this adapter without a separate source
review and provider-budget plan.
"""

from __future__ import annotations

from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import open_circuit

ALPHA_VANTAGE_PROVIDER = "alpha_vantage"
ALPHA_VANTAGE_DISABLED_REASON = (
    "Alpha Vantage free tier는 비활성화돼 있어서 더 이상 호출하지 않아요."
)


def _rate_limited_error(message: str) -> HttpFetchError:
    open_circuit(ALPHA_VANTAGE_PROVIDER, message)
    return HttpFetchError(
        message,
        provider=ALPHA_VANTAGE_PROVIDER,
        retryable=False,
        rate_limited=True,
    )


def _extract_daily_series(payload: dict) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise HttpFetchError("Alpha Vantage 응답 구조가 예상과 달라요.")

    if payload.get("Note"):
        raise _rate_limited_error(f"Alpha Vantage 안내 메시지를 받았어요: {payload['Note']}")
    if payload.get("Information"):
        raise _rate_limited_error(f"Alpha Vantage 안내 정보를 받았어요: {payload['Information']}")
    if payload.get("Error Message"):
        raise HttpFetchError(f"Alpha Vantage 오류 메시지를 받았어요: {payload['Error Message']}")

    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or len(series) < 2:
        raise HttpFetchError("Alpha Vantage 일봉 데이터가 충분하지 않아요.")
    return series


def fetch_daily_close_change_volume(symbol: str, api_key: str) -> tuple[float, float, int]:
    open_circuit(ALPHA_VANTAGE_PROVIDER, ALPHA_VANTAGE_DISABLED_REASON)
    raise HttpFetchError(
        f"{ALPHA_VANTAGE_DISABLED_REASON} 대상={symbol}",
        provider=ALPHA_VANTAGE_PROVIDER,
        retryable=False,
    )


__all__ = [
    "HttpFetchError",
    "fetch_daily_close_change_volume",
]
