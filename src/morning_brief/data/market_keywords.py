"""시장 데이터 기반 키워드 자동 추출 + Grok 키워드 합산."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def extract_market_keywords(market_packet: dict) -> list[str]:
    """수집된 시장 수치에서 오늘 화제 키워드를 자동 생성."""
    keywords: list[str] = []
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%B %d %Y")

    for point in market_packet.get("macro", []):
        label = point.get("label", "")
        change = point.get("change_pct") or 0
        if "VIX" in label and (point.get("price") or 0) > 25:
            keywords.append(f"volatility spike market fear {today}")
        if "US10Y" in point.get("canonical_key", "") and abs(change) > 1.0:
            direction = "surge" if change > 0 else "drop"
            keywords.append(f"treasury yields {direction} {today}")

    for point in market_packet.get("us_indices", []):
        change = point.get("change_pct") or 0
        key = point.get("canonical_key", "")
        if "SPX" in key and abs(change) > 1.5:
            direction = "rally" if change > 0 else "selloff"
            keywords.append(f"S&P 500 {direction} {today}")

    for point in market_packet.get("tech_stocks", []):
        change = point.get("change_pct") or 0
        if abs(change) > 3.0:
            ticker = point.get("ticker", "")
            direction = "surge" if change > 0 else "decline"
            keywords.append(f"{ticker} {direction} {today}")

    btc = market_packet.get("bitcoin", {})
    spot = btc.get("spot", {})
    btc_change = spot.get("change_pct") or 0
    if abs(btc_change) > 3.0:
        direction = "rally" if btc_change > 0 else "drop"
        keywords.append(f"bitcoin {direction} {today}")

    return keywords


_MACRO_HINTS = ("treasury", "fed", "yields", "dollar", "inflation", "rate")
_BTC_HINTS = ("bitcoin", "btc")
_EQUITY_HINTS = ("s&p", "nasdaq", "soxx", "dow")


def build_search_keywords(
    market_keywords: list[str],
    grok_keywords: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """시장 데이터 키워드 + Grok 키워드 합산."""
    result: dict[str, list[str]] = {
        "macro": [],
        "ai_bigtech": [],
        "bitcoin": [],
        "us_equity": [],
    }

    for kw in market_keywords:
        lower = kw.lower()
        if any(h in lower for h in _BTC_HINTS):
            result["bitcoin"].append(kw)
        elif any(h in lower for h in _MACRO_HINTS):
            result["macro"].append(kw)
        elif any(h in lower for h in _EQUITY_HINTS):
            result["us_equity"].append(kw)
        else:
            result["ai_bigtech"].append(kw)

    if grok_keywords:
        for sector, kws in grok_keywords.items():
            if sector in result:
                result[sector].extend(kws)

    return result
