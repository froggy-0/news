from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

from morning_brief.data.market_policy import (
    canonical_key_for,
    canonical_label_for,
    validation_bounds_for,
)
from morning_brief.data.sources.btc_etf_official import (
    fetch_official_btc_etf_snapshots,
    load_official_btc_etf_cache,
    save_official_btc_etf_cache,
)
from morning_brief.data.sources.coingecko import fetch_btc_usd_price_change
from morning_brief.data.sources.fred import fetch_macro_points_from_fred
from morning_brief.data.sources.http_client import get_json_with_retry, is_host_resolvable
from morning_brief.data.sources.provider_runtime import (
    execute_with_provider_retry,
)
from morning_brief.data.sources.stooq import fetch_close_change_and_volume, to_stooq_symbol
from morning_brief.models import BitcoinEtfIssuerSnapshot, BitcoinSnapshot, MarketPoint
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = 1.2
FEAR_GREED_TIMEOUT = 10
YAHOO_FINANCE_HOST = "query2.finance.yahoo.com"
BTC_ETF_OFFICIAL_CACHE_RELATIVE_PATH = Path("btc_etf/official_snapshots.json")
MARKET_POINT_CACHE_RELATIVE_PATH = Path("market/last_success_points.json")
MACRO_FALLBACK_TARGETS = [
    ("us10y", "^TNX", 0.1),
    ("us3m", "^IRX", 1.0),
    ("dxy", "DX-Y.NYB", 1.0),
    ("vix", "^VIX", 1.0),
]
US_INDEX_TARGETS = [
    ("spy", "SPY", "spy.us"),
    ("qqq", "QQQ", "qqq.us"),
    ("soxx", "SOXX", "soxx.us"),
]
TECH_STOCK_TICKERS = [
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
BTC_ETF_TICKERS = ["IBIT", "FBTC", "ARKB", "BITB", "GBTC"]

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
            "Yahoo Finance 주소를 확인하지 못했어요 (%s). yfinance 폴백 값이 0으로 들어갈 수 있어요.",
            YAHOO_FINANCE_HOST,
        )
        raise RuntimeError("Yahoo Finance 주소를 확인하지 못했어요.")

    def fetch_history():
        history = yf.Ticker(ticker).history(
            period=period,
            interval=interval,
            auto_adjust=False,
        )
        if history.empty:
            raise RuntimeError(f"{ticker} 이력 데이터가 비어 있어요.")
        return history

    try:
        return execute_with_provider_retry(
            provider="yfinance",
            operation=fetch_history,
            should_retry=lambda exc: True,
            on_retry=lambda exc, attempt, max_attempts, delay: logger.warning(
                "yfinance 데이터를 다시 가져오는 중이에요 (%s/%s). 대상=%s | %s | sleep=%.2fs",
                attempt,
                max_attempts,
                ticker,
                exc,
                delay,
            ),
            max_attempts=MAX_RETRIES,
            base_backoff_seconds=BACKOFF_SECONDS,
        )
    except Exception as exc:
        raise RuntimeError(f"{ticker} 시장 이력 데이터를 가져오지 못했어요.") from exc


def _latest_price_point_from_yfinance(
    label: str,
    ticker: str,
    canonical_key: str,
    price_scale: float = 1.0,
) -> MarketPoint:
    history = _history_with_retry(ticker=ticker, period="5d", interval="1d")
    if len(history) < 2:
        raise ValueError(f"{ticker} 일봉 데이터가 충분하지 않아요.")

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
        canonical_key=canonical_key,
        raw_value=round(latest_close, 4),
        resolved_value=round(latest_close, 4),
    )


def _market_point(
    label: str,
    ticker: str,
    close: float | None,
    change_pct: float | None,
    *,
    canonical_key: str,
) -> MarketPoint:
    return MarketPoint(
        label=label,
        ticker=ticker,
        price=round(close, 4) if close is not None else None,
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        canonical_key=canonical_key,
        raw_value=round(close, 4) if close is not None else None,
        resolved_value=round(close, 4) if close is not None else None,
    )


def _safe_with_fallback(
    *,
    warning_key: str,
    warning_message: str,
    warning_args: tuple[object, ...],
    primary_fetch,
    fallback_fetch,
):
    try:
        return primary_fetch()
    except Exception as exc:
        _warn_once(warning_key, warning_message, *warning_args, exc)
        return fallback_fetch()


def _safe_yfinance_point(
    label: str,
    ticker: str,
    canonical_key: str | None = None,
    price_scale: float = 1.0,
) -> MarketPoint:
    canonical_key = canonical_key or canonical_key_for(ticker, label)
    try:
        return _latest_price_point_from_yfinance(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
            price_scale=price_scale,
        )
    except Exception as exc:
        _warn_once(
            f"yfinance_fallback_{ticker}",
            "%s (%s) 데이터를 바로 가져오지 못해 비워둘게요: %s",
            label,
            ticker,
            exc,
        )
        return MarketPoint(
            label=label,
            ticker=ticker,
            price=None,
            change_pct=None,
            canonical_key=canonical_key,
            validation_status="missing",
            resolution_reason="원본 데이터를 가져오지 못했어요.",
        )


def _point_from_stooq(
    label: str,
    ticker: str,
    canonical_key: str | None = None,
    stooq_symbol: str | None = None,
) -> MarketPoint:
    canonical_key = canonical_key or canonical_key_for(ticker, stooq_symbol or label)
    symbol = stooq_symbol or to_stooq_symbol(ticker)
    close, change_pct, _ = fetch_close_change_and_volume(symbol)
    return _market_point(
        label=label,
        ticker=ticker,
        close=close,
        change_pct=change_pct,
        canonical_key=canonical_key,
    )


def _point_and_volume_from_stooq(
    label: str,
    ticker: str,
    canonical_key: str | None = None,
    stooq_symbol: str | None = None,
) -> tuple[MarketPoint, int]:
    canonical_key = canonical_key or canonical_key_for(ticker, stooq_symbol or label)
    symbol = stooq_symbol or to_stooq_symbol(ticker)
    close, change_pct, volume = fetch_close_change_and_volume(symbol)
    return (
        _market_point(
            label=label,
            ticker=ticker,
            close=close,
            change_pct=change_pct,
            canonical_key=canonical_key,
        ),
        volume,
    )


def _safe_stooq_point(
    label: str,
    ticker: str,
    canonical_key: str | None = None,
    stooq_symbol: str | None = None,
) -> MarketPoint:
    canonical_key = canonical_key or canonical_key_for(ticker, stooq_symbol or label)
    symbol = stooq_symbol or to_stooq_symbol(ticker)
    return _safe_with_fallback(
        warning_key=f"stooq_fallback_{symbol}",
        warning_message="Stooq에서 %s (%s) 데이터를 바로 가져오지 못해 yfinance로 이어서 볼게요: %s",
        warning_args=(label, symbol),
        primary_fetch=lambda: _point_from_stooq(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
            stooq_symbol=symbol,
        ),
        fallback_fetch=lambda: _safe_yfinance_point(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
        ),
    )


def _volume_from_yfinance(ticker: str) -> int | None:
    try:
        history = _history_with_retry(ticker=ticker, period="2d", interval="1d")
        latest_volume = history["Volume"].iloc[-1]
        if latest_volume == latest_volume:
            return int(latest_volume)
    except Exception as exc:
        _warn_once(
            f"yfinance_volume_fallback_{ticker}",
            "%s 거래량은 yfinance 폴백까지 확인했지만 가져오지 못했어요: %s",
            ticker,
            exc,
        )

    return None


def _safe_stooq_point_and_volume(
    *,
    label: str,
    ticker: str,
    canonical_key: str | None = None,
    stooq_symbol: str | None = None,
) -> tuple[MarketPoint, int | None]:
    canonical_key = canonical_key or canonical_key_for(ticker, stooq_symbol or label)
    symbol = stooq_symbol or to_stooq_symbol(ticker)
    return _safe_with_fallback(
        warning_key=f"stooq_point_volume_fallback_{symbol}",
        warning_message="Stooq에서 %s (%s) 가격과 거래량을 바로 가져오지 못해 yfinance로 이어서 볼게요: %s",
        warning_args=(label, symbol),
        primary_fetch=lambda: _point_and_volume_from_stooq(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
            stooq_symbol=symbol,
        ),
        fallback_fetch=lambda: (
            _safe_yfinance_point(label=label, ticker=ticker, canonical_key=canonical_key),
            _volume_from_yfinance(ticker=ticker),
        ),
    )


def fetch_macro_points(fred_api_key: str = "") -> list[MarketPoint]:
    def _fallback_macro_points(
        existing_canonical_keys: set[str] | None = None,
    ) -> list[MarketPoint]:
        existing = existing_canonical_keys or set()
        # ICE DXY is sourced only from Yahoo Finance's DX-Y.NYB path.
        # Stooq does not expose a compatible symbol, and FRED broad dollar indices
        # are intentionally excluded because they do not match the ICE DXY definition.
        return [
            _safe_yfinance_point(
                label=canonical_label_for(canonical_key),
                ticker=ticker,
                canonical_key=canonical_key_for(ticker, canonical_key),
                price_scale=scale,
            )
            for canonical_key, ticker, scale in MACRO_FALLBACK_TARGETS
            if canonical_key not in existing
        ]

    if fred_api_key:
        try:
            points = fetch_macro_points_from_fred(fred_api_key)
            existing_keys = {point.canonical_key for point in points if point.canonical_key}
            supplemental_points = _fallback_macro_points(existing_keys)
            if supplemental_points:
                logger.info(
                    "거시 지표는 FRED 기준으로 가져오고, 일부 보완 지표(%s)는 yfinance 기준으로 채웠어요.",
                    ", ".join(point.label for point in supplemental_points),
                )
            else:
                logger.info("거시 지표는 FRED 기준으로 가져왔어요.")
            return [*points, *supplemental_points]
        except Exception as exc:
            _warn_once(
                "fred_fallback",
                "FRED에서 거시 지표를 가져오지 못해 yfinance 기준으로 이어서 볼게요: %s",
                exc,
            )

    logger.info("거시 지표는 yfinance 폴백 기준으로 가져왔어요.")
    return _fallback_macro_points()


def fetch_us_index_points() -> list[MarketPoint]:
    # Stooq index symbols are inconsistent; use liquid ETF proxies for stability.
    points = [
        _safe_stooq_point(
            label=canonical_label_for(canonical_key),
            ticker=ticker,
            canonical_key=canonical_key_for(ticker, stooq_symbol, canonical_key),
            stooq_symbol=stooq_symbol,
        )
        for canonical_key, ticker, stooq_symbol in US_INDEX_TARGETS
    ]
    logger.info("미국 지수 흐름은 Stooq 기준으로 보고, 필요하면 yfinance로 보강했어요.")
    return points


def fetch_tech_stock_points() -> list[MarketPoint]:
    points = [
        _safe_stooq_point(
            label=ticker,
            ticker=ticker,
            canonical_key=canonical_key_for(ticker),
        )
        for ticker in TECH_STOCK_TICKERS
    ]
    points.sort(
        key=lambda point: abs(point.change_pct) if point.change_pct is not None else -1.0,
        reverse=True,
    )
    logger.info("기술주는 Stooq 기준으로 보고, 필요하면 yfinance로 보강했어요.")
    return points


def _fetch_fear_greed() -> tuple[int | None, str | None]:
    url = "https://api.alternative.me/fng/?limit=1"
    last_error: Exception | None = None

    try:
        payload = get_json_with_retry(
            url,
            provider="alternative_me",
            timeout=FEAR_GREED_TIMEOUT,
            retries=MAX_RETRIES,
            backoff_seconds=BACKOFF_SECONDS,
        )
        item = payload.get("data", [{}])[0]
        value = int(item.get("value"))
        label = str(item.get("value_classification"))
        return value, label
    except Exception as exc:
        last_error = exc

    _warn_once(
        "fear_greed_fail",
        "공포탐욕지수는 여러 번 확인했지만 이번에는 가져오지 못했어요: %s",
        last_error,
    )
    return None, None


def _fetch_btc_spot_point() -> MarketPoint:
    try:
        price, change_pct = fetch_btc_usd_price_change()
        logger.info("비트코인 현물 가격은 CoinGecko 기준으로 가져왔어요.")
        return MarketPoint(
            label="BTC-USD",
            ticker="BTC-USD",
            price=round(price, 4),
            change_pct=round(change_pct, 2),
            canonical_key=canonical_key_for("BTC-USD"),
            raw_value=round(price, 4),
            resolved_value=round(price, 4),
        )
    except Exception as exc:
        _warn_once(
            "coingecko_btc_fallback",
            "CoinGecko에서 비트코인 가격을 가져오지 못해 yfinance로 이어서 볼게요: %s",
            exc,
        )
        return _safe_yfinance_point(
            label="BTC-USD",
            ticker="BTC-USD",
            canonical_key=canonical_key_for("BTC-USD"),
        )


def _official_btc_etf_cache_file(cache_dir: Path) -> Path:
    return cache_dir / BTC_ETF_OFFICIAL_CACHE_RELATIVE_PATH


def _market_point_cache_file(cache_dir: Path) -> Path:
    return cache_dir / MARKET_POINT_CACHE_RELATIVE_PATH


def _normalize_point_state(point: MarketPoint) -> MarketPoint:
    if point.price is None:
        return replace(
            point,
            change_pct=point.change_pct if point.change_pct is not None else None,
            raw_value=point.raw_value,
            resolved_value=None,
            validation_status=point.validation_status or "missing",
        )

    return replace(
        point,
        raw_value=point.raw_value if point.raw_value is not None else point.price,
        resolved_value=point.resolved_value if point.resolved_value is not None else point.price,
        validation_status=point.validation_status or "ok",
    )


def _load_market_point_cache(cache_file: Path) -> dict[str, MarketPoint]:
    if not cache_file.exists():
        return {}

    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    cached: dict[str, MarketPoint] = {}
    for canonical_key, item in payload.items():
        if not isinstance(item, dict):
            continue
        try:
            cached[str(canonical_key)] = _normalize_point_state(MarketPoint(**item))
        except TypeError:
            continue
    return cached


def _save_market_point_cache(cache_file: Path, points: list[MarketPoint]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        point.canonical_key: asdict(
            replace(
                _normalize_point_state(point),
                is_previous_value=False,
                validation_status="ok",
                resolution_reason="",
            )
        )
        for point in points
        if (
            point.canonical_key
            and point.price is not None
            and not point.is_previous_value
            and _point_is_within_expected_range(point)
        )
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_point_from_cache(
    point: MarketPoint,
    previous_by_key: dict[str, MarketPoint],
) -> MarketPoint:
    normalized = _normalize_point_state(point)
    if normalized.price is not None:
        return normalized

    previous = previous_by_key.get(normalized.canonical_key)
    if previous is None or previous.price is None:
        return replace(
            normalized,
            is_previous_value=False,
            validation_status="missing",
            raw_value=None,
            resolved_value=None,
            resolution_reason="원본 데이터와 마지막 성공 값이 모두 없어 생략했어요.",
        )

    restored = _normalize_point_state(previous)
    return replace(
        normalized,
        price=restored.price,
        change_pct=restored.change_pct,
        is_previous_value=True,
        validation_status="previous_value",
        raw_value=None,
        resolved_value=restored.price,
        resolution_reason="원본 데이터가 없어 마지막 성공 값으로 대체했어요.",
    )


def _resolve_points_from_cache(
    points: list[MarketPoint],
    previous_by_key: dict[str, MarketPoint],
) -> list[MarketPoint]:
    return [_resolve_point_from_cache(point, previous_by_key) for point in points]


def _sum_available_volumes(volumes: list[int | None]) -> int | None:
    available = [volume for volume in volumes if volume is not None]
    if not available:
        return None
    return sum(available)


def _point_is_within_expected_range(point: MarketPoint) -> bool:
    if point.price is None:
        return False

    bounds = validation_bounds_for(point.canonical_key)
    if bounds is None:
        return True

    lower, upper = bounds
    return lower <= point.price <= upper


def _format_bounds(bounds: tuple[float, float]) -> str:
    lower, upper = bounds
    return f"{lower:g}~{upper:g}"


def _validate_market_point(point: MarketPoint) -> tuple[MarketPoint, str | None]:
    normalized = _normalize_point_state(point)
    candidate_value = normalized.price

    if candidate_value is None:
        reason = (
            normalized.resolution_reason or "원본 데이터와 마지막 성공 값이 모두 없어 생략했어요."
        )
        validated = replace(
            normalized,
            validation_status="missing",
            raw_value=normalized.raw_value,
            resolved_value=None,
            resolution_reason=reason,
        )
        return validated, f"{validated.label}는 {reason}"

    bounds = validation_bounds_for(normalized.canonical_key)
    if bounds is not None and not (bounds[0] <= candidate_value <= bounds[1]):
        bounds_text = _format_bounds(bounds)
        if normalized.is_previous_value:
            reason = f"마지막 성공 값도 허용 범위({bounds_text})를 벗어나 생략했어요."
            raw_value = normalized.raw_value
        else:
            reason = (
                f"원본 값 {candidate_value:,.2f}가 허용 범위({bounds_text})를 벗어나 생략했어요."
            )
            raw_value = (
                normalized.raw_value if normalized.raw_value is not None else candidate_value
            )
        validated = replace(
            normalized,
            price=None,
            change_pct=None,
            validation_status="anomaly",
            raw_value=raw_value,
            resolved_value=None,
            resolution_reason=reason,
        )
        return validated, f"{validated.label}는 {reason}"

    if normalized.is_previous_value:
        return (
            replace(
                normalized,
                validation_status="previous_value",
                resolved_value=candidate_value,
            ),
            None,
        )

    return (
        replace(
            normalized,
            validation_status="ok",
            raw_value=normalized.raw_value if normalized.raw_value is not None else candidate_value,
            resolved_value=candidate_value,
            resolution_reason="",
        ),
        None,
    )


def _validate_market_points(points: list[MarketPoint]) -> tuple[list[MarketPoint], list[str]]:
    validated_points: list[MarketPoint] = []
    notes: list[str] = []
    for point in points:
        validated, note = _validate_market_point(point)
        validated_points.append(validated)
        if note:
            notes.append(note)
    return validated_points, notes


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
    perplexity_api_key: str = "",
    observer: PipelineObserver | None = None,
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
        snapshots = fetch_official_btc_etf_snapshots(
            api_key=perplexity_api_key,
            observer=observer,
        )
    except Exception as exc:
        _warn_once(
            "btc_etf_official_fallback",
            "Perplexity 기준 BTC ETF 참조 데이터를 가져오지 못했어요: %s",
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


def fetch_bitcoin_snapshot(
    cache_dir: Path | None = None,
    perplexity_api_key: str = "",
    observer: PipelineObserver | None = None,
) -> BitcoinSnapshot:
    spot = _fetch_btc_spot_point()
    volumes: list[int | None] = []

    etf_points = []
    for ticker in BTC_ETF_TICKERS:
        point, volume = _safe_stooq_point_and_volume(
            label=ticker,
            ticker=ticker,
        )
        etf_points.append(point)
        volumes.append(volume)

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
        spot_price_usd=spot.price or 0.0,
        perplexity_api_key=perplexity_api_key,
        observer=observer,
    )

    return BitcoinSnapshot(
        spot=spot,
        etf_points=etf_points,
        etf_total_volume=_sum_available_volumes(volumes),
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
    perplexity_api_key: str = "",
    cache_dir: Path | None = None,
    observer: PipelineObserver | None = None,
) -> dict:
    effective_cache_dir = cache_dir or Path(".cache").resolve()
    cache_file = _market_point_cache_file(effective_cache_dir)
    previous_by_key = _load_market_point_cache(cache_file)
    macro_points = fetch_macro_points(fred_api_key=fred_api_key)
    us_index_points = fetch_us_index_points()
    tech_stock_points = fetch_tech_stock_points()
    btc_snapshot = fetch_bitcoin_snapshot(
        cache_dir=effective_cache_dir,
        perplexity_api_key=perplexity_api_key,
        observer=observer,
    )
    all_current_points = [
        *macro_points,
        *us_index_points,
        *tech_stock_points,
        btc_snapshot.spot,
        *btc_snapshot.etf_points,
    ]
    macro_points = _resolve_points_from_cache(macro_points, previous_by_key)
    us_index_points = _resolve_points_from_cache(us_index_points, previous_by_key)
    tech_stock_points = _resolve_points_from_cache(tech_stock_points, previous_by_key)
    btc_snapshot.spot = _resolve_point_from_cache(btc_snapshot.spot, previous_by_key)
    btc_snapshot.etf_points = _resolve_points_from_cache(btc_snapshot.etf_points, previous_by_key)
    _save_market_point_cache(cache_file, all_current_points)
    macro_points, macro_notes = _validate_market_points(macro_points)
    us_index_points, index_notes = _validate_market_points(us_index_points)
    tech_stock_points, tech_notes = _validate_market_points(tech_stock_points)
    validated_spot, spot_note = _validate_market_point(btc_snapshot.spot)
    validated_etf_points, etf_notes = _validate_market_points(btc_snapshot.etf_points)
    btc_snapshot.spot = validated_spot
    btc_snapshot.etf_points = validated_etf_points
    data_footer_notes = [
        *macro_notes,
        *index_notes,
        *tech_notes,
        *([spot_note] if spot_note else []),
        *etf_notes,
    ]
    packet = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "macro": [point.__dict__ for point in macro_points],
        "us_indices": [point.__dict__ for point in us_index_points],
        "tech_stocks": [point.__dict__ for point in tech_stock_points],
        "data_footer_notes": data_footer_notes,
        "bitcoin": {
            "spot": btc_snapshot.spot.__dict__,
            "etf_points": [point.__dict__ for point in btc_snapshot.etf_points],
            "etf_total_volume": btc_snapshot.etf_total_volume,
            "fear_greed_value": btc_snapshot.fear_greed_value,
            "fear_greed_label": btc_snapshot.fear_greed_label,
            "official_etf_snapshots": [
                snapshot.__dict__ for snapshot in btc_snapshot.official_etf_snapshots
            ],
            "official_etf_total_btc": btc_snapshot.official_etf_total_btc,
            "official_etf_total_aum_usd": btc_snapshot.official_etf_total_aum_usd,
            "official_etf_daily_flow_btc": btc_snapshot.official_etf_daily_flow_btc,
            "official_etf_daily_flow_usd": btc_snapshot.official_etf_daily_flow_usd,
            "official_etf_supported_tickers": btc_snapshot.official_etf_supported_tickers,
            "official_etf_compared_tickers": btc_snapshot.official_etf_compared_tickers,
        },
    }
    if observer is not None:
        observer.record_market_anomalies(packet)
    return packet
