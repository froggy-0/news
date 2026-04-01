"""
unified_output.py — 이메일·대시보드 공통 데이터 계약 (SSOT)

Phase 1: QuantitativeLayer / NarrativeLayer / MetaLayer / UnifiedOutput dataclass 정의
         + packet_to_quantitative() / briefing_to_narrative() 변환 함수

DO NOT redefine packet / briefing variable names inside this module
(소비 측 코드와 혼동 방지).
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any

from morning_brief.brief_formatting import (
    extract_sections,
    parse_event_calendar,
    parse_sector_mapping,
)
from morning_brief.data.market_policy import is_rate_canonical_key
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 포맷 표준 상수 (FC-1 ~ FC-4)
# FC-1: change_pct  → f"{v:+.2f}%"   (소수 2자리, 부호 포함)
# FC-2: total_btc   → f"{v:,.2f}"    (소수 2자리, 천 단위 구분)
# FC-3: BTC 가격    → f"${v:,.0f}"   (정수, $ 접두어)
# FC-4: change_bps  → f"{v:+.0f}bp"  (정수, 부호 포함)
# ---------------------------------------------------------------------------

# 공개 스냅샷 스펙: (packet_section, canonical_key, symbol, label)
_SNAPSHOT_SPECS = (
    ("macro", "us10y", "US10Y", "미국 10년물"),
    ("macro", "dxy", "DXY", "달러 인덱스"),
    ("macro", "vix", "VIX", "VIX"),
    ("korea_watch", "usdkrw", "KRW", "원/달러 환율"),
    ("korea_watch", "nq_futures", "NQ1!", "나스닥 선물"),
    ("us_indices", "spy", "SPX", "S&P 500"),
    ("us_indices", "qqq", "QQQ", "나스닥 100"),
    ("us_indices", "soxx", "SOXX", "반도체 ETF"),
)


# ---------------------------------------------------------------------------
# 내부 헬퍼 — public_site.py 동일 로직을 이 모듈에서 독립적으로 사용
# ---------------------------------------------------------------------------


def _resolved_price(point: dict[str, Any]) -> float | None:
    if not isinstance(point, dict):
        return None
    resolved = point.get("resolved_value")
    if isinstance(resolved, (float, int)) and math.isfinite(resolved):
        return float(resolved)
    price = point.get("price")
    if isinstance(price, (float, int)) and math.isfinite(price):
        return float(price)
    return None


def _change_pct(point: dict[str, Any]) -> float | None:
    raw = point.get("change_pct")
    if isinstance(raw, (float, int)) and math.isfinite(raw):
        return float(raw)
    return None


def _change_bps(point: dict[str, Any]) -> float | None:
    raw = point.get("change_bps")
    if isinstance(raw, (float, int)) and math.isfinite(raw):
        return float(raw)
    return None


def _trend(point: dict[str, Any], canonical_key: str) -> str | None:
    if is_rate_canonical_key(canonical_key):
        bps = _change_bps(point)
        if bps is None:
            return None
        return "up" if bps > 0 else ("down" if bps < 0 else "neutral")
    pct = _change_pct(point)
    if pct is None:
        return None
    return "up" if pct > 0 else ("down" if pct < 0 else "neutral")


def _format_value(canonical_key: str, price: float | None) -> str | None:
    if price is None:
        return None
    if canonical_key == "btc":
        return f"${price:,.0f}"  # FC-3
    if canonical_key in {"usdkrw", "nq_futures", "spy", "qqq", "soxx"}:
        return f"{price:,.2f}"
    if is_rate_canonical_key(canonical_key):
        return f"{price:.2f}%"
    return f"{price:.2f}"


def _format_change(canonical_key: str, point: dict[str, Any]) -> str | None:
    if is_rate_canonical_key(canonical_key):
        bps = _change_bps(point)
        if bps is None:
            return None
        return f"{bps:+.0f}bp"  # FC-4
    pct = _change_pct(point)
    if pct is None:
        return None
    return f"{pct:+.2f}%"  # FC-1


def _synthetic_history(canonical_key: str, point: dict[str, Any]) -> list[float]:
    """
    2포인트 sparkline 생성 (_synthetic_history from public_site.py 동일 로직).
    """
    price = _resolved_price(point)
    if price is None:
        return []

    if is_rate_canonical_key(canonical_key):
        bps = _change_bps(point)
        if bps is None:
            return []
        previous = price - (bps / 100.0)
        return [round(previous, 4), round(price, 4)]

    pct = _change_pct(point)
    if pct is None or pct <= -100:
        return []
    previous = price / (1 + (pct / 100.0))
    return [round(previous, 4), round(price, 4)]


def _find_point(points: list[dict[str, Any]], canonical_key: str) -> dict[str, Any] | None:
    for point in points:
        if str(point.get("canonical_key", "")).strip() == canonical_key:
            return point
    return None


def _is_cached(point: dict[str, Any]) -> bool:
    return (
        bool(point.get("is_previous_value"))
        or str(point.get("validation_status", "")).strip() == "previous_value"
    )


# ---------------------------------------------------------------------------
# Task 1.1 — QuantitativeLayer
# ---------------------------------------------------------------------------


@dataclass
class TickerPoint:
    """단일 시장 지표 포인트.

    포맷 표준:
    - FC-1: change_pct  → f"{v:+.2f}%"  (rate 종목은 FC-4: f"{v:+.0f}bp")
    - FC-3: value_fmt은 btc일 경우 f"${v:,.0f}"
    - FC-4: change_bps  → f"{v:+.0f}bp"
    """

    symbol: str
    label: str
    value_fmt: str | None  # display-ready 가격 문자열
    change: str | None  # FC-1 or FC-4
    trend: str | None  # "up" / "down" / "neutral"
    is_cached: bool
    sparkline: list[float]


@dataclass
class ETFIssuerPoint:
    """BTC ETF 발행사별 공식 보유 현황.

    FC-2: btc_held → f"{v:,.0f}" (정수, 천 단위 구분)
    """

    issuer: str  # 발행사 이름
    ticker: str  # 티커 심볼
    btc_held: str | None  # FC-2: "570,234"
    aum: str | None  # "$35,000,000"
    source_url: str


@dataclass
class QuantitativeLayer:
    """정량 데이터 레이어.

    포맷 표준 (FC-1~FC-4):
    - FC-1: change_pct  → f"{v:+.2f}%"
    - FC-2: btc_total_holding  → f"{v:,.2f} BTC"
    - FC-3: btc_price  → f"${v:,.0f}"
    - FC-4: change_bps  → f"{v:+.0f}bp"
    """

    # 거시 지표
    us10y: TickerPoint | None
    dxy: TickerPoint | None
    vix: TickerPoint | None
    # 원/달러 + 나스닥 선물 (korea_watch)
    usdkrw: TickerPoint | None
    nq_futures: TickerPoint | None
    # 미국 지수
    spy: TickerPoint | None
    qqq: TickerPoint | None
    soxx: TickerPoint | None
    # BTC 현물 (TickerPoint)
    btc_spot: TickerPoint | None
    # BTC ETF 집계 (FC-2, FC-3)
    btc_total_holding: str | None  # FC-2: "570,234.56 BTC"
    btc_total_aum_usd: str | None  # "$XX,XXX,XXX"
    btc_etf_issuers: list  # list[ETFIssuerPoint] — 발행사별 보유 현황
    btc_fear_greed_value: int | None
    btc_fear_greed_label: str | None
    # sparkline_data: canonical_key → [prev, current]
    sparkline_data: dict[str, list[float]]


# ---------------------------------------------------------------------------
# Task 1.2 — NarrativeLayer
# ---------------------------------------------------------------------------


@dataclass
class NarrativeLayer:
    """서사 데이터 레이어.

    공통 필드: 이메일·대시보드 양쪽에서 소비.
    이메일 전용 optional 필드: None 이면 대시보드 소비 시 absent 처리.
    """

    # 공통 필드
    news: list[dict]
    x_signals: list[dict]
    topic_summaries: dict
    headline: str
    summary_lead: str
    summary_support: str
    key_narrative: str | None
    briefing_markdown: str | None

    # 이메일 전용 optional (기본값 None — absent 처리)
    sector_mapping: Any = None
    event_calendar: Any = None
    issue_briefings: Any = None
    weekly_context: str | None = None
    sonar_analyses: Any = None


# ---------------------------------------------------------------------------
# Task 1.3 — MetaLayer
# ---------------------------------------------------------------------------

_TRANSLATION_STATUS_VALUES = frozenset({"ok", "partial", "failed", "skipped"})


@dataclass
class MetaLayer:
    """파이프라인 메타 정보.

    translation_status 허용값: "ok" | "partial" | "failed" | "skipped"
    """

    run_at: str  # ISO 8601
    pipeline_version: str
    source_counts: dict
    translation_status: str  # "ok" | "partial" | "failed" | "skipped"

    def __post_init__(self) -> None:
        if self.translation_status not in _TRANSLATION_STATUS_VALUES:
            # TODO: clarify - 잘못된 값 진입 시 skipped로 강제 처리 vs 예외
            log_structured(
                logger,
                event="fallback.used",
                message="MetaLayer.translation_status 허용값 외 값을 skipped로 보정했어요.",
                level=logging.WARNING,
                invalid_translation_status=self.translation_status,
                reason="invalid_translation_status",
            )
            self.translation_status = "skipped"


# ---------------------------------------------------------------------------
# Task 1.4 — UnifiedOutput
# ---------------------------------------------------------------------------


@dataclass
class UnifiedOutput:
    """이메일·대시보드 양쪽이 소비하는 단일 진실 공급원(SSOT) 컨테이너."""

    quantitative: QuantitativeLayer
    narrative: NarrativeLayer
    meta: MetaLayer

    def to_dict(self) -> dict:
        """R2 persist 용 JSON 직렬화."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Task 2 — packet → QuantitativeLayer 변환
# ---------------------------------------------------------------------------


def packet_to_quantitative(packet: dict) -> QuantitativeLayer:
    """LLM 텍스트 경유 없이 packet raw 값을 직접 QuantitativeLayer로 매핑.

    DO NOT extract numbers via regex from LLM text — raw packet values only.
    """
    packet_sections: dict[str, list] = {
        "macro": packet.get("macro") or [],
        "korea_watch": packet.get("korea_watch") or [],
        "us_indices": packet.get("us_indices") or [],
    }

    sparkline_data: dict[str, list[float]] = {}

    def _build_ticker(
        section_name: str, canonical_key: str, symbol: str, label: str
    ) -> TickerPoint | None:
        raw = packet_sections.get(section_name, [])
        if not isinstance(raw, list):
            return None
        point = _find_point(raw, canonical_key)
        if point is None:
            return None
        sparkline = _synthetic_history(canonical_key, point)
        sparkline_data[canonical_key] = sparkline
        return TickerPoint(
            symbol=symbol,
            label=label,
            value_fmt=_format_value(canonical_key, _resolved_price(point)),
            change=_format_change(canonical_key, point),
            trend=_trend(point, canonical_key),
            is_cached=_is_cached(point),
            sparkline=sparkline,
        )

    # 거시 지표 + 원/달러 + 미국 지수
    us10y = _build_ticker("macro", "us10y", "US10Y", "미국 10년물")
    dxy = _build_ticker("macro", "dxy", "DXY", "달러 인덱스")
    vix = _build_ticker("macro", "vix", "VIX", "VIX")
    usdkrw = _build_ticker("korea_watch", "usdkrw", "KRW", "원/달러 환율")
    nq_futures = _build_ticker("korea_watch", "nq_futures", "NQ1!", "나스닥 선물")
    spy = _build_ticker("us_indices", "spy", "SPX", "S&P 500")
    qqq = _build_ticker("us_indices", "qqq", "QQQ", "나스닥 100")
    soxx = _build_ticker("us_indices", "soxx", "SOXX", "반도체 ETF")

    # BTC 현물
    btc_raw = packet.get("bitcoin") or {}
    if not isinstance(btc_raw, dict):
        btc_raw = {}

    btc_spot_raw = btc_raw.get("spot") or {}
    btc_spot: TickerPoint | None = None
    if isinstance(btc_spot_raw, dict) and btc_spot_raw:
        btc_sparkline = _synthetic_history("btc", btc_spot_raw)
        sparkline_data["btc"] = btc_sparkline
        btc_spot = TickerPoint(
            symbol="BTC",
            label="비트코인 현물",
            value_fmt=_format_value("btc", _resolved_price(btc_spot_raw)),  # FC-3
            change=_format_change("btc", btc_spot_raw),  # FC-1
            trend=_trend(btc_spot_raw, "btc"),
            is_cached=_is_cached(btc_spot_raw),
            sparkline=btc_sparkline,
        )

    # BTC ETF 집계 (FC-2)
    total_btc = btc_raw.get("official_etf_total_btc")
    total_aum = btc_raw.get("official_etf_total_aum_usd")
    btc_total_holding: str | None = (
        f"{float(total_btc):,.2f} BTC" if isinstance(total_btc, (float, int)) else None
    )
    btc_total_aum_usd: str | None = (
        f"${float(total_aum):,.0f}" if isinstance(total_aum, (float, int)) else None
    )

    # BTC ETF 발행사별 보유 현황
    btc_etf_issuers: list[ETFIssuerPoint] = []
    for snap in btc_raw.get("official_etf_snapshots", []):
        if not isinstance(snap, dict):
            continue
        snap_total_btc = snap.get("total_btc")
        snap_aum_usd = snap.get("aum_usd")
        btc_etf_issuers.append(
            ETFIssuerPoint(
                issuer=str(snap.get("issuer", "")).strip(),
                ticker=str(snap.get("ticker", "")).strip(),
                btc_held=f"{float(snap_total_btc):,.0f}"
                if isinstance(snap_total_btc, (float, int))
                else None,
                aum=f"${float(snap_aum_usd):,.0f}"
                if isinstance(snap_aum_usd, (float, int))
                else None,
                source_url=str(snap.get("source_url", "")).strip(),
            )
        )

    # Fear & Greed
    fear_value = btc_raw.get("fear_greed_value")
    fear_label = str(btc_raw.get("fear_greed_label", "") or "").strip()
    btc_fear_greed_value: int | None = fear_value if isinstance(fear_value, int) else None
    btc_fear_greed_label: str | None = fear_label or None

    return QuantitativeLayer(
        us10y=us10y,
        dxy=dxy,
        vix=vix,
        usdkrw=usdkrw,
        nq_futures=nq_futures,
        spy=spy,
        qqq=qqq,
        soxx=soxx,
        btc_spot=btc_spot,
        btc_total_holding=btc_total_holding,
        btc_total_aum_usd=btc_total_aum_usd,
        btc_etf_issuers=btc_etf_issuers,
        btc_fear_greed_value=btc_fear_greed_value,
        btc_fear_greed_label=btc_fear_greed_label,
        sparkline_data=sparkline_data,
    )


# ---------------------------------------------------------------------------
# Task 3 — briefing + packet → NarrativeLayer 변환
# ---------------------------------------------------------------------------


def _parse_issue_briefings(section_4_1: str) -> list[dict]:
    """Section 4-1 이슈 브리핑 파싱 (emailer.py 동일 로직)."""
    if not section_4_1.strip():
        return []
    briefings: list[dict] = []
    current_topic = ""
    current_lines: list[str] = []

    for line in section_4_1.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_topic and current_lines:
                briefings.append({"topic": current_topic, "body": "\n".join(current_lines).strip()})
                current_topic = ""
                current_lines = []
            continue
        if not current_topic:
            current_topic = stripped
        else:
            current_lines.append(stripped)

    if current_topic and current_lines:
        briefings.append({"topic": current_topic, "body": "\n".join(current_lines).strip()})
    return briefings


def _parse_sonar(section_5_2: str) -> list[dict] | None:
    """Section 5-2 Sonar 교차 분석 파싱 (emailer.py 동일 로직)."""
    if not section_5_2.strip():
        return None
    analyses: list[dict] = []
    current_lines: list[str] = []

    for line in section_5_2.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_lines:
                analyses.append({"body": "\n".join(current_lines).strip()})
                current_lines = []
            continue
        current_lines.append(stripped)

    if current_lines:
        analyses.append({"body": "\n".join(current_lines).strip()})
    return analyses[:3] if analyses else None


def _split_hero(raw: str) -> tuple[str, str]:
    """section_0 텍스트를 (첫 줄=headline, 나머지=summary_support)로 분리."""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if not lines:
        return "", ""
    return lines[0], "\n".join(lines[1:])


def briefing_to_narrative(
    briefing: str,
    packet: dict,
    public_context: dict | None = None,
) -> NarrativeLayer:
    """B3/B4 결과를 NarrativeLayer로 매핑.

    DO NOT extract numbers via regex — 수치는 QuantitativeLayer 전용 경로 사용.
    """
    # 섹션 파싱
    try:
        section_map = extract_sections(briefing)
    except Exception:
        log_structured(
            logger,
            event="error.raised",
            message="briefing_to_narrative에서 extract_sections가 실패해 빈 섹션맵을 사용할게요.",
            level=logging.ERROR,
            reason="extract_sections_failed",
        )
        section_map = {}

    # section_0: 30초 요약 → headline / summary_lead / summary_support
    section_0 = section_map.get("section_0", "") or ""
    headline, summary_support = _split_hero(section_0)
    summary_lead = section_0.strip()

    # key_narrative: sonar_context에서 추출 (packet raw)
    sonar_ctx = packet.get("sonar_context") or {}
    key_narrative: str | None = None
    if isinstance(sonar_ctx, dict):
        kn = sonar_ctx.get("key_narrative") or sonar_ctx.get("summary") or ""
        key_narrative = str(kn).strip() or None

    # news / x_signals — public_context 우선, 없으면 packet fallback
    # 주의: public_context["all_news"] = [] (빈 리스트)는 "필터 후 0건"을 의미하므로
    # falsy로 취급해 packet fallback으로 넘어가면 안 됨 — is not None으로 명시 비교
    if isinstance(public_context, dict):
        _public_news = public_context.get("all_news")
        raw_news = _public_news if _public_news is not None else (packet.get("news") or [])
        _public_signals = public_context.get("all_x_signals")
        raw_signals = (
            _public_signals
            if _public_signals is not None
            else (packet.get("x_market_signals") or [])
        )
    else:
        raw_news = packet.get("news") or []
        raw_signals = packet.get("x_market_signals") or []

    news: list[dict] = [item for item in raw_news if isinstance(item, dict)]
    x_signals: list[dict] = [item for item in raw_signals if isinstance(item, dict)]

    # topic_summaries
    topic_summaries_raw = packet.get("topic_summaries") or {}
    topic_summaries: dict = topic_summaries_raw if isinstance(topic_summaries_raw, dict) else {}

    # 이메일 전용 optional 필드 (파싱 실패 시 None — 예외 전파 금지)
    try:
        issue_briefings: list[dict] | None = (
            _parse_issue_briefings(section_map.get("section_4_1", "") or "") or None
        )
    except Exception:
        log_structured(
            logger,
            event="error.raised",
            message="briefing_to_narrative에서 issue_briefings 파싱이 실패했어요.",
            level=logging.ERROR,
            reason="issue_briefings_parse_failed",
        )
        issue_briefings = None

    try:
        sector_mapping_raw = section_map.get("section_4_3", "") or ""
        sector_mapping = (
            parse_sector_mapping(sector_mapping_raw) if sector_mapping_raw.strip() else None
        )
    except Exception:
        log_structured(
            logger,
            event="error.raised",
            message="briefing_to_narrative에서 sector_mapping 파싱이 실패했어요.",
            level=logging.ERROR,
            reason="sector_mapping_parse_failed",
        )
        sector_mapping = None

    try:
        weekly_context_raw = section_map.get("section_5_1", "") or ""
        weekly_context: str | None = weekly_context_raw.strip() or None
    except Exception:
        log_structured(
            logger,
            event="error.raised",
            message="briefing_to_narrative에서 weekly_context 추출이 실패했어요.",
            level=logging.ERROR,
            reason="weekly_context_parse_failed",
        )
        weekly_context = None

    try:
        sonar_analyses = _parse_sonar(section_map.get("section_5_2", "") or "")
    except Exception:
        log_structured(
            logger,
            event="error.raised",
            message="briefing_to_narrative에서 sonar_analyses 파싱이 실패했어요.",
            level=logging.ERROR,
            reason="sonar_analyses_parse_failed",
        )
        sonar_analyses = None

    try:
        event_calendar_raw = section_map.get("section_6", "") or ""
        events = parse_event_calendar(event_calendar_raw) if event_calendar_raw.strip() else []
        event_calendar = events if events else None
    except Exception:
        log_structured(
            logger,
            event="error.raised",
            message="briefing_to_narrative에서 event_calendar 파싱이 실패했어요.",
            level=logging.ERROR,
            reason="event_calendar_parse_failed",
        )
        event_calendar = None

    return NarrativeLayer(
        news=news,
        x_signals=x_signals,
        topic_summaries=topic_summaries,
        headline=headline,
        summary_lead=summary_lead,
        summary_support=summary_support,
        key_narrative=key_narrative,
        briefing_markdown=briefing,
        sector_mapping=sector_mapping,
        event_calendar=event_calendar,
        issue_briefings=issue_briefings,
        weekly_context=weekly_context,
        sonar_analyses=sonar_analyses,
    )
