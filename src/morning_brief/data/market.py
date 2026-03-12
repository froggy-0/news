from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import time

import requests
import yfinance as yf

from morning_brief.data.sources.alpha_vantage import fetch_daily_close_change_volume
from morning_brief.data.sources.btc_etf_official import (
    fetch_official_btc_etf_snapshots,
    load_official_btc_etf_cache,
    save_official_btc_etf_cache,
)
from morning_brief.data.sources.coingecko import fetch_btc_usd_price_change
from morning_brief.data.sources.fred import fetch_macro_points_from_fred
from morning_brief.data.sources.http_client import HttpFetchError, is_host_resolvable
from morning_brief.data.sources.stooq import fetch_close_change_and_volume, to_stooq_symbol
from morning_brief.models import BitcoinEtfIssuerSnapshot, BitcoinSnapshot, MarketPoint

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = 1.2
FEAR_GREED_TIMEOUT = 10
YAHOO_FINANCE_HOST = "query2.finance.yahoo.com"
BTC_ETF_OFFICIAL_CACHE_RELATIVE_PATH = Path("btc_etf/official_snapshots.json")

# yfinance tries to write cache files under user cache directory by default.
# In restricted environments (CI/sandbox), use /tmp to avoid permission issues.
try:
    if hasattr(yf, "set_tz_cache_location"):
        cache_dir = Path("/tmp/py-yfinance-cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))
except Exception:
    pass

_provider_warned: set[str] = set()



def _warn_once(key: str, message: str, *args) -> None:
    if key in _provider_warned:
        return
    _provider_warned.add(key)
    logger.warning(message, *args)



def _history_with_retry(ticker: str, period: str, interval: str):
    if not is_host_resolvable(YAHOO_FINANCE_HOST):
        _warn_once(
            "yahoo_dns",
            "Yahoo Finance host resolution failed (%s). yfinance fallbacks may return zeros.",
            YAHOO_FINANCE_HOST,
        )
        raise RuntimeError("Yahoo Finance host resolution failed")

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            history = yf.Ticker(ticker).history(
                period=period,
                interval=interval,
                auto_adjust=False,
            )
            if history.empty:
                raise ValueError(f"No history for {ticker}")
            return history
        except Exception as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            logger.warning(
                "yfinance retry %s/%s failed for %s: %s",
                attempt,
                MAX_RETRIES,
                ticker,
                exc,
            )
            time.sleep(BACKOFF_SECONDS * attempt)

    raise RuntimeError(f"Failed to fetch market history for {ticker}") from last_error



def _latest_price_point_from_yfinance(
    label: str,
    ticker: str,
    price_scale: float = 1.0,
) -> MarketPoint:
    history = _history_with_retry(ticker=ticker, period="5d", interval="1d")
    if len(history) < 2:
        raise ValueError(f"Insufficient daily history for {ticker}")

    latest_close = float(history["Close"].iloc[-1]) * price_scale
    previous_close = float(history["Close"].iloc[-2]) * price_scale
    if previous_close == 0:
        change_pct = 0.0
    else:
        change_pct = ((latest_close - previous_close) / previous_close) * 100

    return MarketPoint(
        label=label,
        ticker=ticker,
        price=round(latest_close, 4),
        change_pct=round(change_pct, 2),
    )



def _safe_yfinance_point(
    label: str,
    ticker: str,
    price_scale: float = 1.0,
) -> MarketPoint:
    try:
        return _latest_price_point_from_yfinance(
            label=label,
            ticker=ticker,
            price_scale=price_scale,
        )
    except Exception as exc:
        _warn_once(
            f"yfinance_fallback_{ticker}",
            "Using zero fallback for %s (%s): %s",
            label,
            ticker,
            exc,
        )
        return MarketPoint(label=label, ticker=ticker, price=0.0, change_pct=0.0)



def _safe_stooq_point(label: str, ticker: str, stooq_symbol: str | None = None) -> MarketPoint:
    symbol = stooq_symbol or to_stooq_symbol(ticker)
    try:
        close, change_pct, _ = fetch_close_change_and_volume(symbol)
        return MarketPoint(
            label=label,
            ticker=ticker,
            price=round(close, 4),
            change_pct=round(change_pct, 2),
        )
    except (HttpFetchError, ValueError) as exc:
        _warn_once(
            f"stooq_fallback_{symbol}",
            "Stooq fetch failed for %s (%s): %s. Falling back to yfinance.",
            label,
            symbol,
            exc,
        )
        return _safe_yfinance_point(label=label, ticker=ticker)



def _safe_alpha_vantage_point(label: str, ticker: str, api_key: str) -> MarketPoint:
    try:
        close, change_pct, _ = fetch_daily_close_change_volume(ticker, api_key)
        return MarketPoint(
            label=label,
            ticker=ticker,
            price=round(close, 4),
            change_pct=round(change_pct, 2),
        )
    except (HttpFetchError, ValueError) as exc:
        _warn_once(
            f"alpha_vantage_fallback_{ticker}",
            "Alpha Vantage fetch failed for %s (%s): %s. Falling back to Stooq/yfinance.",
            label,
            ticker,
            exc,
        )
        return _safe_stooq_point(label=label, ticker=ticker)


def _safe_stooq_volume(ticker: str, stooq_symbol: str | None = None) -> int:
    symbol = stooq_symbol or to_stooq_symbol(ticker)
    try:
        _, _, volume = fetch_close_change_and_volume(symbol)
        return volume
    except (HttpFetchError, ValueError) as exc:
        _warn_once(
            f"stooq_volume_fallback_{symbol}",
            "Stooq volume fetch failed for %s: %s. Falling back to yfinance.",
            symbol,
            exc,
        )

    try:
        history = _history_with_retry(ticker=ticker, period="2d", interval="1d")
        latest_volume = history["Volume"].iloc[-1]
        if latest_volume == latest_volume:
            return int(latest_volume)
    except Exception as exc:
        _warn_once(
            f"yfinance_volume_fallback_{ticker}",
            "Skipping volume for %s after yfinance fallback failure: %s",
            ticker,
            exc,
        )

    return 0


def _safe_alpha_vantage_volume(ticker: str, api_key: str) -> int:
    try:
        _, _, volume = fetch_daily_close_change_volume(ticker, api_key)
        return volume
    except (HttpFetchError, ValueError) as exc:
        _warn_once(
            f"alpha_vantage_volume_fallback_{ticker}",
            "Alpha Vantage volume fetch failed for %s: %s. Falling back to Stooq/yfinance.",
            ticker,
            exc,
        )
        return _safe_stooq_volume(ticker=ticker)


def fetch_macro_points(fred_api_key: str = "") -> list[MarketPoint]:
    if fred_api_key:
        try:
            points = fetch_macro_points_from_fred(fred_api_key)
            logger.info("Macro provider: FRED")
            return points
        except Exception as exc:
            _warn_once(
                "fred_fallback",
                "FRED macro fetch failed (%s). Falling back to yfinance macros.",
                exc,
            )

    targets = [
        ("미국 10년물 국채금리", "^TNX", 0.1),
        ("미국 13주물 단기금리", "^IRX", 1.0),
        ("달러 인덱스", "DX-Y.NYB", 1.0),
        ("VIX", "^VIX", 1.0),
    ]
    logger.info("Macro provider: yfinance fallback")
    return [
        _safe_yfinance_point(label=label, ticker=ticker, price_scale=scale)
        for label, ticker, scale in targets
    ]



def fetch_us_index_points(alpha_vantage_api_key: str = "") -> list[MarketPoint]:
    # Stooq index symbols are inconsistent; use liquid ETF proxies for stability.
    targets = [
        ("S&P500", "SPY", "spy.us"),
        ("NASDAQ", "QQQ", "qqq.us"),
        ("반도체 섹터 (SOXX)", "SOXX", "soxx.us"),
    ]
    if alpha_vantage_api_key:
        points = [
            _safe_alpha_vantage_point(label=label, ticker=ticker, api_key=alpha_vantage_api_key)
            for label, ticker, _ in targets
        ]
        logger.info("US index provider: Alpha Vantage (ETF proxies) with Stooq/yfinance fallback")
        return points

    points = [
        _safe_stooq_point(label=label, ticker=ticker, stooq_symbol=stooq_symbol)
        for label, ticker, stooq_symbol in targets
    ]
    logger.info("US index provider: Stooq (ETF proxies) with yfinance fallback")
    return points



def fetch_tech_stock_points(alpha_vantage_api_key: str = "") -> list[MarketPoint]:
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
    if alpha_vantage_api_key:
        points = [
            _safe_alpha_vantage_point(label=ticker, ticker=ticker, api_key=alpha_vantage_api_key)
            for ticker in tickers
        ]
        points.sort(key=lambda x: abs(x.change_pct), reverse=True)
        logger.info("Tech stock provider: Alpha Vantage with Stooq/yfinance fallback")
        return points

    points = [_safe_stooq_point(label=ticker, ticker=ticker) for ticker in tickers]
    points.sort(key=lambda x: abs(x.change_pct), reverse=True)
    logger.info("Tech stock provider: Stooq with yfinance fallback")
    return points



def _fetch_fear_greed() -> tuple[int | None, str | None]:
    url = "https://api.alternative.me/fng/?limit=1"
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=FEAR_GREED_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            item = payload.get("data", [{}])[0]
            value = int(item.get("value"))
            label = str(item.get("value_classification"))
            return value, label
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            time.sleep(BACKOFF_SECONDS * attempt)

    _warn_once(
        "fear_greed_fail",
        "Fear&Greed fetch failed after retries: %s",
        last_error,
    )
    return None, None



def _fetch_btc_spot_point() -> MarketPoint:
    try:
        price, change_pct = fetch_btc_usd_price_change()
        logger.info("BTC spot provider: CoinGecko")
        return MarketPoint(
            label="BTC-USD",
            ticker="BTC-USD",
            price=round(price, 4),
            change_pct=round(change_pct, 2),
        )
    except Exception as exc:
        _warn_once(
            "coingecko_btc_fallback",
            "CoinGecko BTC fetch failed: %s. Falling back to yfinance.",
            exc,
        )
        return _safe_yfinance_point(label="BTC-USD", ticker="BTC-USD")



def _official_btc_etf_cache_file(cache_dir: Path) -> Path:
    return cache_dir / BTC_ETF_OFFICIAL_CACHE_RELATIVE_PATH


def _summarize_official_btc_etf_snapshots(
    snapshots: list[BitcoinEtfIssuerSnapshot],
    previous_by_ticker: dict[str, BitcoinEtfIssuerSnapshot],
    spot_price_usd: float,
) -> tuple[float | None, float | None, float | None, float | None, list[str]]:
    if not snapshots:
        return None, None, None, None, []

    total_btc = sum(snapshot.total_btc for snapshot in snapshots)
    total_aum_usd = sum(snapshot.aum_usd for snapshot in snapshots)
    compared_tickers: list[str] = []
    flow_btc = 0.0

    for snapshot in snapshots:
        previous = previous_by_ticker.get(snapshot.ticker)
        if previous is None:
            continue
        compared_tickers.append(snapshot.ticker)
        flow_btc += snapshot.total_btc - previous.total_btc

    flow_usd = flow_btc * spot_price_usd if compared_tickers else None
    return (
        round(total_btc, 8),
        round(total_aum_usd, 2),
        round(flow_btc, 8) if compared_tickers else None,
        round(flow_usd, 2) if flow_usd is not None else None,
        compared_tickers,
    )


def _fetch_official_btc_etf_data(
    *,
    cache_dir: Path,
    spot_price_usd: float,
) -> tuple[
    list[BitcoinEtfIssuerSnapshot],
    float | None,
    float | None,
    float | None,
    float | None,
    list[str],
]:
    cache_file = _official_btc_etf_cache_file(cache_dir)
    previous_by_ticker = load_official_btc_etf_cache(cache_file)

    try:
        snapshots = fetch_official_btc_etf_snapshots()
    except Exception as exc:
        _warn_once(
            "btc_etf_official_fallback",
            "Official BTC ETF issuer fetch failed: %s",
            exc,
        )
        snapshots = []

    if not snapshots:
        return [], None, None, None, None, []

    save_official_btc_etf_cache(cache_file, snapshots)
    return (
        snapshots,
        *_summarize_official_btc_etf_snapshots(
            snapshots=snapshots,
            previous_by_ticker=previous_by_ticker,
            spot_price_usd=spot_price_usd,
        ),
    )


def fetch_bitcoin_snapshot(alpha_vantage_api_key: str = "", cache_dir: Path | None = None) -> BitcoinSnapshot:
    spot = _fetch_btc_spot_point()

    etf_tickers = ["IBIT", "FBTC", "ARKB", "BITB", "GBTC"]
    if alpha_vantage_api_key:
        etf_points = [
            _safe_alpha_vantage_point(label=ticker, ticker=ticker, api_key=alpha_vantage_api_key)
            for ticker in etf_tickers
        ]
    else:
        etf_points = [_safe_stooq_point(label=ticker, ticker=ticker) for ticker in etf_tickers]

    volume_total = 0
    for ticker in etf_tickers:
        if alpha_vantage_api_key:
            volume_total += _safe_alpha_vantage_volume(ticker=ticker, api_key=alpha_vantage_api_key)
        else:
            volume_total += _safe_stooq_volume(ticker=ticker)

    fear_greed_value, fear_greed_label = _fetch_fear_greed()
    (
        official_snapshots,
        official_total_btc,
        official_total_aum_usd,
        official_daily_flow_btc,
        official_daily_flow_usd,
        official_compared_tickers,
    ) = _fetch_official_btc_etf_data(
        cache_dir=cache_dir or Path(".cache").resolve(),
        spot_price_usd=spot.price,
    )

    return BitcoinSnapshot(
        spot=spot,
        etf_points=etf_points,
        etf_total_volume=volume_total,
        fear_greed_value=fear_greed_value,
        fear_greed_label=fear_greed_label,
        official_etf_snapshots=official_snapshots,
        official_etf_total_btc=official_total_btc,
        official_etf_total_aum_usd=official_total_aum_usd,
        official_etf_daily_flow_btc=official_daily_flow_btc,
        official_etf_daily_flow_usd=official_daily_flow_usd,
        official_etf_supported_tickers=[snapshot.ticker for snapshot in official_snapshots],
        official_etf_compared_tickers=official_compared_tickers,
    )



def build_market_packet(
    fred_api_key: str = "",
    alpha_vantage_api_key: str = "",
    cache_dir: Path | None = None,
) -> dict:
    btc_snapshot = fetch_bitcoin_snapshot(
        alpha_vantage_api_key=alpha_vantage_api_key,
        cache_dir=cache_dir,
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "macro": [point.__dict__ for point in fetch_macro_points(fred_api_key=fred_api_key)],
        "us_indices": [
            point.__dict__
            for point in fetch_us_index_points(alpha_vantage_api_key=alpha_vantage_api_key)
        ],
        "tech_stocks": [
            point.__dict__
            for point in fetch_tech_stock_points(alpha_vantage_api_key=alpha_vantage_api_key)
        ],
        "bitcoin": {
            "spot": btc_snapshot.spot.__dict__,
            "etf_points": [point.__dict__ for point in btc_snapshot.etf_points],
            "etf_total_volume": btc_snapshot.etf_total_volume,
            "fear_greed_value": btc_snapshot.fear_greed_value,
            "fear_greed_label": btc_snapshot.fear_greed_label,
            "official_etf_snapshots": [snapshot.__dict__ for snapshot in btc_snapshot.official_etf_snapshots],
            "official_etf_total_btc": btc_snapshot.official_etf_total_btc,
            "official_etf_total_aum_usd": btc_snapshot.official_etf_total_aum_usd,
            "official_etf_daily_flow_btc": btc_snapshot.official_etf_daily_flow_btc,
            "official_etf_daily_flow_usd": btc_snapshot.official_etf_daily_flow_usd,
            "official_etf_supported_tickers": btc_snapshot.official_etf_supported_tickers,
            "official_etf_compared_tickers": btc_snapshot.official_etf_compared_tickers,
        },
    }
