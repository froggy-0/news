from __future__ import annotations

from datetime import datetime, timezone

import requests
import yfinance as yf

from morning_brief.models import BitcoinSnapshot, MarketPoint


def _latest_price_point(label: str, ticker: str, price_scale: float = 1.0) -> MarketPoint:
    history = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
    if history.empty or len(history) < 2:
        raise ValueError(f"No recent price history for {ticker}")

    latest_close = float(history["Close"].iloc[-1]) * price_scale
    previous_close = float(history["Close"].iloc[-2]) * price_scale
    change_pct = ((latest_close - previous_close) / previous_close) * 100

    return MarketPoint(
        label=label,
        ticker=ticker,
        price=round(latest_close, 4),
        change_pct=round(change_pct, 2),
    )


def _safe_price_point(label: str, ticker: str, price_scale: float = 1.0) -> MarketPoint:
    try:
        return _latest_price_point(label, ticker, price_scale=price_scale)
    except Exception:
        return MarketPoint(label=label, ticker=ticker, price=0.0, change_pct=0.0)



def fetch_macro_points() -> list[MarketPoint]:
    targets = [
        ("미국 10년물 국채금리", "^TNX", 0.1),
        ("미국 13주물 단기금리", "^IRX", 1.0),
        ("달러 인덱스", "DX-Y.NYB", 1.0),
        ("VIX", "^VIX", 1.0),
    ]
    return [
        _safe_price_point(label, ticker, price_scale=price_scale)
        for label, ticker, price_scale in targets
    ]



def fetch_us_index_points() -> list[MarketPoint]:
    targets = [
        ("S&P500", "^GSPC"),
        ("NASDAQ", "^IXIC"),
        ("반도체 섹터 (SOXX)", "SOXX"),
    ]
    return [_safe_price_point(label, ticker) for label, ticker in targets]



def fetch_tech_stock_points() -> list[MarketPoint]:
    tickers = [
        "NVDA",
        "MSFT",
        "AAPL",
        "AMZN",
        "GOOGL",
        "META",
        "AMD",
        "TSM",
        "ASML",
        "AVGO",
    ]
    points: list[MarketPoint] = []
    for ticker in tickers:
        points.append(_safe_price_point(ticker, ticker))

    points.sort(key=lambda x: abs(x.change_pct), reverse=True)
    return points



def _fetch_fear_greed() -> tuple[int | None, str | None]:
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        item = payload.get("data", [{}])[0]
        value = int(item.get("value"))
        label = str(item.get("value_classification"))
        return value, label
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None, None



def fetch_bitcoin_snapshot() -> BitcoinSnapshot:
    spot = _safe_price_point("BTC-USD", "BTC-USD")

    etf_tickers = ["IBIT", "FBTC", "ARKB", "BITB", "GBTC"]
    etf_points = [_safe_price_point(ticker, ticker) for ticker in etf_tickers]

    volume_total = 0
    for ticker in etf_tickers:
        try:
            history = yf.Ticker(ticker).history(period="2d", interval="1d", auto_adjust=False)
            if history.empty:
                continue
            latest_volume = history["Volume"].iloc[-1]
            if latest_volume == latest_volume:  # NaN-safe check
                volume_total += int(latest_volume)
        except Exception:
            continue

    fear_greed_value, fear_greed_label = _fetch_fear_greed()

    return BitcoinSnapshot(
        spot=spot,
        etf_points=etf_points,
        etf_total_volume=volume_total,
        fear_greed_value=fear_greed_value,
        fear_greed_label=fear_greed_label,
    )



def build_market_packet() -> dict:
    btc_snapshot = fetch_bitcoin_snapshot()
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "macro": [point.__dict__ for point in fetch_macro_points()],
        "us_indices": [point.__dict__ for point in fetch_us_index_points()],
        "tech_stocks": [point.__dict__ for point in fetch_tech_stock_points()],
        "bitcoin": {
            "spot": btc_snapshot.spot.__dict__,
            "etf_points": [point.__dict__ for point in btc_snapshot.etf_points],
            "etf_total_volume": btc_snapshot.etf_total_volume,
            "fear_greed_value": btc_snapshot.fear_greed_value,
            "fear_greed_label": btc_snapshot.fear_greed_label,
        },
    }
