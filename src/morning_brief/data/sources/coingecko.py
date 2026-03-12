from __future__ import annotations

from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"



def fetch_btc_usd_price_change() -> tuple[float, float]:
    payload = get_json_with_retry(
        COINGECKO_SIMPLE_PRICE_URL,
        params={
            "ids": "bitcoin",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
        timeout=20,
    )

    btc = payload.get("bitcoin")
    if not isinstance(btc, dict):
        raise HttpFetchError("Invalid CoinGecko response: missing bitcoin key")

    price_raw = btc.get("usd")
    change_raw = btc.get("usd_24h_change", 0.0)
    if not isinstance(price_raw, (int, float)):
        raise HttpFetchError("Invalid CoinGecko response: missing usd price")

    try:
        change_pct = float(change_raw)
    except (TypeError, ValueError):
        change_pct = 0.0

    return float(price_raw), change_pct


__all__ = [
    "HttpFetchError",
    "fetch_btc_usd_price_change",
]
