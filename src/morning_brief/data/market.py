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
    is_rate_canonical_key,
    normalize_change_bps,
    validation_bounds_for,
)
from morning_brief.data.sources.btc_etf_official import (
    fetch_official_btc_etf_snapshots,
    save_official_btc_etf_cache,
    save_official_btc_etf_cache_state,
)
from morning_brief.data.sources.coingecko import fetch_btc_usd_price_change
from morning_brief.data.sources.fred import fetch_macro_points_from_fred
from morning_brief.data.sources.http_client import get_json_with_retry, is_host_resolvable
from morning_brief.data.sources.provider_runtime import (
    execute_with_provider_retry,
)
from morning_brief.data.sources.stooq import fetch_close_change_and_volume, to_stooq_symbol
from morning_brief.logging_utils import log_structured
from morning_brief.models import BitcoinEtfIssuerSnapshot, BitcoinSnapshot, MarketPoint
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = 1.2
FEAR_GREED_TIMEOUT = 10
YAHOO_FINANCE_HOST = "query2.finance.yahoo.com"
BTC_ETF_OFFICIAL_CACHE_RELATIVE_PATH = Path("btc_etf/official_snapshots.json")
MARKET_POINT_CACHE_RELATIVE_PATH = Path("market/last_success_points.json")
# 운영용 cache state는 유지하지만, stale snapshot을 사용자-facing 값에는 재사용하지 않는다.
BTC_ETF_CACHE_MAX_AGE_HOURS = 48
MARKET_POINT_CACHE_MAX_AGE_HOURS = 26
MACRO_FALLBACK_TARGETS = [
    ("us10y", "^TNX", 0.1),
    # DEPRECATED: dxy yfinance DX=F — ICE Dollar Futures, 비공식 스크래퍼, 현물 DXY 괴리
    # DEPRECATED: dxy yfinance DX-Y.NYB — 상장폐지
    # REPLACED BY: FRED DTWEXAFEGS (일별, 연준 공식)
    ("dxy", "DX=F", 1.0),
    ("vix", "^VIX", 1.0),
]
KOREA_INVESTOR_TARGETS = [
    ("usdkrw", "KRW=X", 1.0),
    ("nq_futures", "NQ=F", 1.0),
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


def _point_changes(
    *,
    canonical_key: str,
    latest_value: float,
    previous_value: float,
) -> tuple[float | None, float | None]:
    if is_rate_canonical_key(canonical_key):
        return None, normalize_change_bps((latest_value - previous_value) * 100)

    if previous_value == 0:
        return 0.0, None

    return round(((latest_value - previous_value) / previous_value) * 100, 2), None


def reset_market_warned_state() -> None:
    """스케줄러 모드에서 매 실행마다 경고를 다시 표시하도록 상태를 초기화합니다."""
    _provider_warned.clear()


def _warn_once(key: str, message: str, *args) -> None:
    if key in _provider_warned:
        return
    _provider_warned.add(key)
    rendered_message = message % args if args else message
    log_structured(
        logger,
        event="fallback.used",
        message=rendered_message,
        level=logging.WARNING,
        reason=key,
    )


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
            on_retry=lambda exc, attempt, max_attempts, delay: log_structured(
                logger,
                event="provider.retry",
                message="yfinance 데이터를 다시 가져오는 중이에요.",
                level=logging.WARNING,
                provider="yfinance",
                attempt=attempt,
                max_attempts=max_attempts,
                ticker=ticker,
                reason=str(exc),
                retryable=True,
                delay_seconds=delay,
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
    history = _history_with_retry(ticker=ticker, period="7d", interval="1d")
    if len(history) < 2:
        raise ValueError(f"{ticker} 일봉 데이터가 충분하지 않아요.")

    latest_close = float(history["Close"].iloc[-1]) * price_scale
    previous_close = float(history["Close"].iloc[-2]) * price_scale
    change_pct, change_bps = _point_changes(
        canonical_key=canonical_key,
        latest_value=latest_close,
        previous_value=previous_close,
    )

    return MarketPoint(
        label=label,
        ticker=ticker,
        price=round(latest_close, 4),
        change_pct=change_pct,
        change_bps=change_bps,
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
    change_bps: float | None = None,
) -> MarketPoint:
    normalized_change_bps = None
    if change_bps is not None:
        normalized_change_bps = (
            normalize_change_bps(change_bps)
            if is_rate_canonical_key(canonical_key)
            else round(change_bps, 2)
        )
    return MarketPoint(
        label=label,
        ticker=ticker,
        price=round(close, 4) if close is not None else None,
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        change_bps=normalized_change_bps,
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
            change_bps=None,
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
        # ICE DXY is sourced from Yahoo Finance's DX=F (ICE Dollar Index Futures) path.
        # The previous DX-Y.NYB ticker was delisted; DX=F tracks the same ICE DXY
        # and is actively maintained. Stooq does not expose a compatible symbol,
        # and FRED broad dollar indices are intentionally excluded because they
        # do not match the ICE DXY definition.
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
                log_structured(
                    logger,
                    event="fallback.used",
                    message="거시 지표는 FRED 기준으로 가져오고 일부 보완 지표는 yfinance 기준으로 채웠어요.",
                    level=logging.DEBUG,
                    provider="fred",
                    filled_labels=", ".join(point.label for point in supplemental_points),
                )
            else:
                log_structured(
                    logger,
                    event="selection.complete",
                    message="거시 지표는 FRED 기준으로 가져왔어요.",
                    level=logging.DEBUG,
                    provider="fred",
                )
            return [*points, *supplemental_points]
        except Exception as exc:
            _warn_once(
                "fred_fallback",
                "FRED에서 거시 지표를 가져오지 못해 yfinance 기준으로 이어서 볼게요: %s",
                exc,
            )

    log_structured(
        logger,
        event="fallback.used",
        message="거시 지표는 yfinance 폴백 기준으로 가져왔어요.",
        level=logging.DEBUG,
        provider="yfinance",
    )
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
    log_structured(
        logger,
        event="selection.complete",
        message="미국 지수 흐름은 Stooq 기준으로 보고 필요하면 yfinance로 보강했어요.",
        level=logging.DEBUG,
        provider="stooq",
        kept_count=len(points),
    )
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
    log_structured(
        logger,
        event="selection.complete",
        message="기술주는 Stooq 기준으로 보고 필요하면 yfinance로 보강했어요.",
        level=logging.DEBUG,
        provider="stooq",
        kept_count=len(points),
    )
    return points


def fetch_newsletter_display_data(
    cache_dir: Path | None = None,
) -> dict:
    """뉴스레터 렌더링 직전에만 호출하는 표시 전용 데이터 수집 함수.

    감성 분석 파이프라인(LLM 프롬프트)에서 제외된 항목:
    - 빅테크 10종 가격 (tech_stocks)
    - BTC ETF 가격 5종 (btc_etf_points)
    - nq_futures / usdkrw (korea_watch)
    """
    korea_watch = fetch_korea_investor_points()
    tech_stocks = fetch_tech_stock_points()
    btc_etf_points: list[MarketPoint] = []
    for ticker in BTC_ETF_TICKERS:
        point, _ = _safe_stooq_point_and_volume(
            label=ticker,
            ticker=ticker,
        )
        btc_etf_points.append(point)

    effective_cache_dir = cache_dir or Path(".cache").resolve()
    cache_file = _market_point_cache_file(effective_cache_dir)
    previous_by_key = _load_market_point_cache(cache_file)

    korea_watch = _resolve_points_from_cache(korea_watch, previous_by_key)
    tech_stocks = _resolve_points_from_cache(tech_stocks, previous_by_key)
    btc_etf_points = _resolve_points_from_cache(btc_etf_points, previous_by_key)
    korea_watch, _ = _validate_market_points(korea_watch)
    tech_stocks, _ = _validate_market_points(tech_stocks)
    btc_etf_points, _ = _validate_market_points(btc_etf_points)

    return {
        "korea_watch": [point.__dict__ for point in korea_watch],
        "tech_stocks": [point.__dict__ for point in tech_stocks],
        "btc_etf_points": [point.__dict__ for point in btc_etf_points],
    }


def fetch_korea_investor_points() -> list[MarketPoint]:
    points = [
        _safe_yfinance_point(
            label=canonical_label_for(canonical_key),
            ticker=ticker,
            canonical_key=canonical_key_for(ticker, canonical_key),
            price_scale=scale,
        )
        for canonical_key, ticker, scale in KOREA_INVESTOR_TARGETS
    ]
    log_structured(
        logger,
        event="selection.complete",
        message="한국 투자자 참고 지표는 yfinance 기준으로 가져왔어요.",
        level=logging.DEBUG,
        provider="yfinance",
        kept_count=len(points),
    )
    return points


def _fear_greed_level_label(value: int | None) -> str | None:
    if value is None:
        return None
    if 0 <= value <= 25:
        return "극단적 공포"
    if 26 <= value <= 45:
        return "공포"
    if 46 <= value <= 55:
        return "중립"
    if 56 <= value <= 75:
        return "탐욕"
    if 76 <= value <= 100:
        return "극단적 탐욕"
    return None


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
        label = _fear_greed_level_label(value)
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
        log_structured(
            logger,
            event="selection.complete",
            message="비트코인 현물 가격은 CoinGecko 기준으로 가져왔어요.",
            level=logging.DEBUG,
            provider="coingecko",
        )
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
            change_bps=point.change_bps if point.change_bps is not None else None,
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


def _load_market_point_cache(
    cache_file: Path,
    *,
    max_age_hours: int = MARKET_POINT_CACHE_MAX_AGE_HOURS,
) -> dict[str, MarketPoint]:
    if not cache_file.exists():
        return {}

    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    meta = payload.pop("_meta", None)
    if isinstance(meta, dict) and isinstance(meta.get("cached_at"), str):
        try:
            cached_at = datetime.fromisoformat(meta["cached_at"])
            age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                log_structured(
                    logger,
                    event="cache.stale",
                    message=f"시장 포인트 캐시가 {age_hours:.1f}시간 경과하여 오래됐습니다 (임계값 {max_age_hours}h). 이전 값을 사용합니다.",
                    level=logging.WARNING,
                    age_hours=round(age_hours, 1),
                    max_age_hours=max_age_hours,
                )
        except (ValueError, TypeError):
            pass

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
    data = {
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
    payload: dict = {"_meta": {"cached_at": datetime.now(timezone.utc).isoformat()}, **data}
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
        change_bps=restored.change_bps,
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
            change_bps=None,
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
) -> tuple[float | None, float | None]:
    if not snapshots:
        return None, None

    total_btc = sum(snapshot.total_btc for snapshot in snapshots)
    total_aum_usd = sum(snapshot.aum_usd for snapshot in snapshots)
    return round(total_btc, 8), round(total_aum_usd, 2)


def _fetch_official_btc_etf_data(
    *,
    cache_dir: Path,
    perplexity_api_key: str = "",
    observer: PipelineObserver | None = None,
) -> tuple[
    list[BitcoinEtfIssuerSnapshot],
    float | None,
    float | None,
]:
    cache_file = _official_btc_etf_cache_file(cache_dir)
    empty_reason = "empty_snapshots"

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
        empty_reason = f"fetch_error:{type(exc).__name__}"

    if not snapshots:
        save_official_btc_etf_cache_state(
            cache_file.parent,
            snapshot_count=0,
            reason=empty_reason,
        )
        log_structured(
            logger,
            event="selection.complete",
            message="BTC ETF 공식 스냅샷이 비어 있어 캐시 상태만 남길게요.",
            reason=empty_reason,
            kept_count=0,
        )
        if observer is not None:
            observer.log_event(
                "btc_etf_reference_empty",
                cache_dir=str(cache_file.parent),
                reason=empty_reason,
            )
        return [], None, None

    save_official_btc_etf_cache(cache_file, snapshots)
    return (
        snapshots,
        *_summarize_official_btc_etf_snapshots(snapshots=snapshots),
    )


def fetch_bitcoin_snapshot(
    cache_dir: Path | None = None,
    perplexity_api_key: str = "",
    observer: PipelineObserver | None = None,
    *,
    fetch_etf_prices: bool = False,
) -> BitcoinSnapshot:
    """BTC 스냅샷 수집.

    fetch_etf_prices=False (기본값): 감성 분석 파이프라인용 — spot + fear_greed + official_snapshots
    fetch_etf_prices=True: 뉴스레터 렌더링용 — ETF 가격 5종 포함 (fetch_newsletter_display_data에서 호출)
    """
    spot = _fetch_btc_spot_point()

    etf_points: list[MarketPoint] = []
    if fetch_etf_prices:
        for ticker in BTC_ETF_TICKERS:
            point, _ = _safe_stooq_point_and_volume(
                label=ticker,
                ticker=ticker,
            )
            etf_points.append(point)

    fear_greed_value, fear_greed_label = _fetch_fear_greed()
    (
        official_snapshots,
        official_total_btc,
        official_total_aum_usd,
    ) = _fetch_official_btc_etf_data(
        cache_dir=cache_dir or Path(".cache").resolve(),
        perplexity_api_key=perplexity_api_key,
        observer=observer,
    )

    return BitcoinSnapshot(
        spot=spot,
        etf_points=etf_points,
        fear_greed_value=fear_greed_value,
        fear_greed_label=fear_greed_label,
        official_etf_snapshots=official_snapshots,
        official_etf_total_btc=official_total_btc,
        official_etf_total_aum_usd=official_total_aum_usd,
    )


def build_market_packet(
    fred_api_key: str = "",
    perplexity_api_key: str = "",
    cache_dir: Path | None = None,
    observer: PipelineObserver | None = None,
    cache_max_age_hours: int = MARKET_POINT_CACHE_MAX_AGE_HOURS,
) -> dict:
    """감성 분석 파이프라인용 시장 패킷.

    포함: macro(us10y, us2y, dxy, vix, hy_spread), us_indices, btc(spot + fear_greed + official_snapshots)
    제외: tech_stocks, korea_watch(usdkrw/nq_futures), btc etf_prices
          → fetch_newsletter_display_data()에서 뉴스레터 렌더링 직전에 수집
    """
    effective_cache_dir = cache_dir or Path(".cache").resolve()
    cache_file = _market_point_cache_file(effective_cache_dir)
    previous_by_key = _load_market_point_cache(cache_file, max_age_hours=cache_max_age_hours)
    macro_points = fetch_macro_points(fred_api_key=fred_api_key)
    us_index_points = fetch_us_index_points()
    btc_snapshot = fetch_bitcoin_snapshot(
        cache_dir=effective_cache_dir,
        perplexity_api_key=perplexity_api_key,
        observer=observer,
        fetch_etf_prices=False,
    )
    all_current_points = [
        *macro_points,
        *us_index_points,
        btc_snapshot.spot,
    ]
    macro_points = _resolve_points_from_cache(macro_points, previous_by_key)
    us_index_points = _resolve_points_from_cache(us_index_points, previous_by_key)
    btc_snapshot.spot = _resolve_point_from_cache(btc_snapshot.spot, previous_by_key)
    _save_market_point_cache(cache_file, all_current_points)
    macro_points, macro_notes = _validate_market_points(macro_points)
    us_index_points, index_notes = _validate_market_points(us_index_points)
    validated_spot, spot_note = _validate_market_point(btc_snapshot.spot)
    btc_snapshot.spot = validated_spot

    # yield_spread: us10y - us2y (장단기 금리차). 음수 = 장단기 역전 = 경기침체 우려 시그널
    _macro_by_key = {p.canonical_key: p for p in macro_points}
    _us10y = _macro_by_key.get("us10y")
    _us2y = _macro_by_key.get("us2y")
    if (
        _us10y is not None
        and _us10y.price is not None
        and _us2y is not None
        and _us2y.price is not None
    ):
        yield_spread: float | None = round(_us10y.price - _us2y.price, 4)
    else:
        yield_spread = None

    data_footer_notes = [
        *macro_notes,
        *index_notes,
        *([spot_note] if spot_note else []),
    ]
    if perplexity_api_key and not btc_snapshot.official_etf_snapshots:
        data_footer_notes.append("BTC ETF 공식 보유 현황은 이번 집계에서는 확인되지 않았어요.")
    packet = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "macro": [point.__dict__ for point in macro_points],
        "yield_spread": yield_spread,  # 장단기 금리차 (10Y-2Y). 음수 = 역전 = 경기침체 우려
        "korea_watch": [],
        "us_indices": [point.__dict__ for point in us_index_points],
        "tech_stocks": [],
        "data_footer_notes": data_footer_notes,
        "bitcoin": {
            "spot": btc_snapshot.spot.__dict__,
            "etf_points": [],
            "fear_greed_value": btc_snapshot.fear_greed_value,
            "fear_greed_label": btc_snapshot.fear_greed_label,
            "official_etf_snapshots": [
                snapshot.__dict__ for snapshot in btc_snapshot.official_etf_snapshots
            ],
            "official_etf_total_btc": btc_snapshot.official_etf_total_btc,
            "official_etf_total_aum_usd": btc_snapshot.official_etf_total_aum_usd,
        },
    }
    if observer is not None:
        observer.record_market_anomalies(packet)
    return packet
