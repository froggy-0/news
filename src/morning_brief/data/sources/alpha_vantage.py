from __future__ import annotations

from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"


def _extract_daily_series(payload: dict) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise HttpFetchError("Unexpected Alpha Vantage payload shape")

    if payload.get("Note"):
        raise HttpFetchError(str(payload["Note"]))
    if payload.get("Information"):
        raise HttpFetchError(str(payload["Information"]))
    if payload.get("Error Message"):
        raise HttpFetchError(str(payload["Error Message"]))

    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or len(series) < 2:
        raise HttpFetchError("Insufficient Alpha Vantage daily time series")
    return series


def fetch_daily_close_change_volume(symbol: str, api_key: str) -> tuple[float, float, int]:
    if not api_key:
        raise ValueError("Alpha Vantage API key is required")

    payload = get_json_with_retry(
        ALPHA_VANTAGE_URL,
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "apikey": api_key,
        },
        timeout=20,
    )
    series = _extract_daily_series(payload)
    dates = sorted(series.keys(), reverse=True)
    latest = series[dates[0]]
    previous = series[dates[1]]

    try:
        latest_close = float(latest["4. close"])
        previous_close = float(previous["4. close"])
        latest_volume = int(float(latest.get("5. volume", 0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpFetchError(f"Invalid Alpha Vantage OHLC data for {symbol}") from exc

    if previous_close == 0:
        change_pct = 0.0
    else:
        change_pct = ((latest_close - previous_close) / previous_close) * 100

    return latest_close, change_pct, latest_volume


__all__ = [
    "HttpFetchError",
    "fetch_daily_close_change_volume",
]
