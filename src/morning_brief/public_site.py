from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from openai import OpenAI

from morning_brief.brief_formatting import extract_sections
from morning_brief.config import Settings
from morning_brief.data.market_policy import is_rate_canonical_key
from morning_brief.logging_utils import log_structured
from morning_brief.observability import PipelineObserver
from morning_brief.openai_utils import usage_snapshot
from morning_brief.unified_output import UnifiedOutput

logger = logging.getLogger(__name__)

_PUBLIC_SNAPSHOT_SPECS = (
    ("macro", "us10y", "US10Y", "미국 10년물"),
    ("macro", "dxy", "DXY", "달러 인덱스"),
    ("macro", "vix", "VIX", "VIX"),
    ("korea_watch", "usdkrw", "KRW", "원/달러 환율"),
    ("korea_watch", "nq_futures", "NQ1!", "나스닥 선물"),
    ("us_indices", "spy", "SPX", "S&P 500"),
    ("us_indices", "qqq", "QQQ", "나스닥 100"),
    ("us_indices", "soxx", "SOXX", "반도체 ETF"),
)

_PUBLIC_TOPIC_SPECS = (
    ("macro", "macro", "거시경제"),
    ("us_equity", "us-stocks", "미국 주식"),
    ("ai_bigtech", "bigtech", "빅테크·AI"),
    ("bitcoin", "bitcoin", "비트코인"),
)

_PUBLIC_NEWS_TOPIC_MAP = {
    "macro": "macro",
    "us_equity": "us-stocks",
    "us-stocks": "us-stocks",
    "ai_bigtech": "bigtech",
    "bigtech": "bigtech",
    "bitcoin": "bitcoin",
}

_EMPTY_INDEX = {"dates": [], "updatedAt": ""}
_SECTION_HEADER_RE = re.compile(r"^(?P<section>\d+(?:-\d+)?)\.\s*")
_HANGUL_RE = re.compile(r"[가-힣]")
_DICT_LITERAL_RE = re.compile(r"^\s*[\[{].*[:].*[\]}]\s*$")
_EXCLUDED_BODY_SECTIONS = {"4-2", "4-3", "5-2", "5-3", "6"}
_PUBLIC_FEATURED_NEWS_LIMIT = 5
_PUBLIC_ALL_NEWS_LIMIT = 12
_PUBLIC_FEATURED_X_LIMIT = 6
_PUBLIC_ALL_X_LIMIT = 12
_PUBLIC_TRANSLATION_BATCH_ITEMS = 6
_PUBLIC_TRANSLATION_BATCH_CHARS = 1800
_TRANSLATION_CACHE_FILE = "public_translation_cache.json"
_MIN_PUBLIC_TICKER_ITEMS = 3


@dataclass(frozen=True)
class _PublicBriefArtifacts:
    date_key: str
    brief_relative_path: str
    brief_payload: dict[str, Any]
    index_payload: dict[str, Any]


def publish_public_brief(
    *,
    packet: dict[str, Any],
    briefing: str,
    run_at: datetime,
    settings: Settings,
    observer: PipelineObserver | None = None,
    public_context: dict[str, Any] | None = None,
    unified: UnifiedOutput | None = None,
) -> _PublicBriefArtifacts:
    run_local = run_at.astimezone(ZoneInfo(settings.timezone))
    date_key = run_local.strftime("%Y-%m-%d")
    brief_relative_path = f"briefs/{date_key}.json"
    public_dir = settings.output_dir / "public"

    brief_payload = build_public_brief(
        packet=packet,
        briefing=briefing,
        run_at=run_local,
        settings=settings,
        observer=observer,
        public_context=public_context,
        unified=unified,
    )

    _write_json(public_dir / brief_relative_path, brief_payload)

    client = _public_r2_client(settings)
    if client is not None:
        client.put_json(brief_relative_path, brief_payload)
        dates = client.list_dates()
    else:
        dates = _list_local_dates(public_dir / "briefs")
        if observer is not None:
            observer.log_event(
                "public_brief_upload_skipped",
                reason="R2 공개 버킷 설정이 없어 로컬 산출물만 남겼어요.",
            )

    index_payload = build_public_index(dates=dates, updated_at=run_local.isoformat())
    _write_json(public_dir / "index.json", index_payload)

    if client is not None:
        client.put_json("index.json", index_payload)

    if observer is not None:
        observer.log_event(
            "public_brief_published",
            date=date_key,
            brief_path=brief_relative_path,
            public_dates=dates,
            uploaded=client is not None,
        )

    return _PublicBriefArtifacts(
        date_key=date_key,
        brief_relative_path=brief_relative_path,
        brief_payload=brief_payload,
        index_payload=index_payload,
    )


def build_public_index(*, dates: list[str], updated_at: str) -> dict[str, Any]:
    normalized_dates = sorted(
        {str(date).strip() for date in dates if str(date).strip()},
        reverse=True,
    )
    return {
        "dates": normalized_dates,
        "updatedAt": updated_at,
    }


def build_public_brief(
    *,
    packet: dict[str, Any],
    briefing: str,
    run_at: datetime,
    settings: Settings | None = None,
    observer: PipelineObserver | None = None,
    public_context: dict[str, Any] | None = None,
    unified: UnifiedOutput | None = None,
) -> dict[str, Any]:
    section_map = extract_sections(briefing)
    brief_body = _clean_public_body(_brief_body_without_title(briefing))
    headline = _headline_from_sections(section_map, brief_body)
    summary_lead, summary_support = _judgment_summary(
        section_map=section_map,
        brief_body=brief_body,
        headline=headline,
    )
    topic_summaries = _topic_summaries(packet)
    if unified is not None:
        all_news = _news_items_v2(unified, run_at, limit=_PUBLIC_ALL_NEWS_LIMIT)
        all_x_signals = _x_signals_v2(unified, run_at, limit=_PUBLIC_ALL_X_LIMIT)
    else:
        all_news = _news_items(
            packet,
            run_at,
            public_context=public_context,
            limit=_PUBLIC_ALL_NEWS_LIMIT,
        )
        all_x_signals = _x_signals(
            packet,
            run_at,
            public_context=public_context,
            limit=_PUBLIC_ALL_X_LIMIT,
        )
    headline, summary_lead, summary_support, translation_status = _apply_public_translation(
        headline=headline,
        summary_lead=summary_lead,
        summary_support=summary_support,
        topic_summaries=topic_summaries,
        news_items=all_news,
        x_signals=all_x_signals,
        settings=settings,
        observer=observer,
    )
    display_news = _filter_public_news_for_display(all_news)
    featured_news = display_news[:_PUBLIC_FEATURED_NEWS_LIMIT]
    featured_x_signals = _filter_public_signals_for_display(
        all_x_signals[:_PUBLIC_FEATURED_X_LIMIT]
    )
    headline = _finalize_public_headline(
        headline=headline,
        summary_lead=summary_lead,
        brief_body=brief_body,
        run_at=run_at,
    )
    display_headline = _display_headline(headline)
    summary_lead, summary_support = _finalize_judgment_summary(
        summary_lead=summary_lead,
        summary_support=summary_support,
        brief_body=brief_body,
        headline=display_headline,
    )
    source_counts = _source_counts(
        public_context=public_context,
        all_news=all_news,
        all_x_signals=all_x_signals,
    )
    featured_x_signals_payload = featured_x_signals or None

    return {
        "meta": {
            "date": run_at.strftime("%Y-%m-%d"),
            "generatedAt": run_at.isoformat(),
            "dataQuality": _data_quality_status(packet),
            "qualityNotes": _quality_notes(packet),
            "displayHeadline": display_headline,
            "sourceCounts": source_counts,
            "translationStatus": translation_status,
            "publicNewsAnalysis": (
                packet.get("public_news_analysis")
                or (public_context.get("public_news_analysis") if public_context else None)
            ),
        },
        "marketSnapshot": {
            "items": _market_snapshot_items_v2(unified)
            if unified is not None
            else _market_snapshot_items(packet),
        },
        "aiJudgment": {
            "headline": headline,
            "body": brief_body,
            "summaryLead": summary_lead,
            "summarySupport": summary_support,
        },
        "topicSummaries": topic_summaries,
        "techStocks": _tech_stocks(packet),
        "bitcoin": _bitcoin_section_v2(unified)
        if unified is not None
        else _bitcoin_section(packet),
        "featuredXSignals": featured_x_signals_payload,
        "allXSignals": all_x_signals or None,
        "featuredNews": featured_news,
        "allNews": display_news,
        "xSignals": featured_x_signals_payload,
        "news": featured_news,
    }


def _brief_body_without_title(briefing: str) -> str:
    lines = briefing.replace("\r\n", "\n").splitlines()
    if not lines:
        return briefing.strip()
    first_line = lines[0].strip()
    if first_line.startswith("SOVEREIGN BRIEF"):
        return "\n".join(lines[1:]).strip()
    return briefing.strip()


def _headline_from_sections(section_map: dict[str, str], brief_body: str) -> str:
    section_0 = str(section_map.get("section_0", "")).strip()
    for line in section_0.splitlines():
        candidate = _normalize_public_text(line)
        if candidate and _is_public_headline_candidate(candidate):
            return _headline_excerpt(candidate)
    for paragraph in brief_body.split("\n\n"):
        candidate = _normalize_public_text(paragraph)
        if candidate and _is_public_headline_candidate(candidate):
            return _headline_excerpt(candidate)
    for line in brief_body.splitlines():
        candidate = _normalize_public_text(line)
        if candidate:
            return _headline_excerpt(candidate)
    return "SOVEREIGN BRIEF"


def _display_headline(text: str) -> str:
    normalized = _normalize_public_text(text)
    stripped = re.sub(r"^[\s\-–—•●▪◦①-⑳0-9.]+", "", normalized).strip()
    return stripped or normalized


def _factual_public_headline(run_at: datetime) -> str:
    return f"{run_at.strftime('%Y-%m-%d')} 발행본"


def _headline_excerpt(text: str) -> str:
    normalized = _normalize_public_text(text)
    if not normalized:
        return normalized
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    first_sentence = sentences[0].strip() if sentences else normalized
    return first_sentence or normalized


def _is_public_headline_candidate(text: str) -> bool:
    normalized = _normalize_public_text(text)
    if not normalized:
        return False
    if normalized.startswith("## "):
        return False
    if _SECTION_HEADER_RE.match(normalized):
        return False
    if _is_machine_payload(normalized):
        return False
    if "http://" in normalized or "https://" in normalized:
        return False
    lowered = normalized.lower()
    if lowered.startswith("참고 출처") or lowered.startswith("source:"):
        return False
    return True


def _is_display_headline_usable(text: str) -> bool:
    normalized = _display_headline(text)
    return (
        bool(normalized)
        and _contains_korean(normalized)
        and _is_public_headline_candidate(normalized)
    )


def _finalize_public_headline(
    *,
    headline: str,
    summary_lead: str,
    brief_body: str,
    run_at: datetime,
) -> str:
    for candidate in (headline, summary_lead, *_body_paragraphs(brief_body)):
        normalized = _normalize_public_text(candidate)
        if _is_display_headline_usable(normalized):
            return _display_headline(normalized)
    return _factual_public_headline(run_at)


def _finalize_judgment_summary(
    *,
    summary_lead: str,
    summary_support: str | None,
    brief_body: str,
    headline: str,
) -> tuple[str, str | None]:
    candidates = [summary_lead]
    if summary_support:
        candidates.append(summary_support)
    candidates.extend(_body_paragraphs(brief_body))

    filtered: list[str] = []
    for candidate in candidates:
        normalized = _normalize_public_text(candidate)
        if not normalized:
            continue
        if not _contains_korean(normalized):
            continue
        display = _display_headline(normalized)
        if not display or display == headline:
            continue
        if not _is_public_headline_candidate(display):
            continue
        if display in filtered:
            continue
        filtered.append(display)

    if not filtered:
        return headline, None
    lead = filtered[0]
    support = filtered[1] if len(filtered) > 1 else None
    return lead, support


def _judgment_summary(
    *,
    section_map: dict[str, str],
    brief_body: str,
    headline: str,
) -> tuple[str, str | None]:
    cleaned_headline = _display_headline(headline)
    section_0 = str(section_map.get("section_0", "")).strip()
    lines = [
        _normalize_public_text(line)
        for line in section_0.splitlines()
        if _normalize_public_text(line)
    ]
    filtered = [
        line
        for line in lines
        if line not in {"0. 오늘의 핵심", "오늘의 핵심"}
        and _display_headline(line) != cleaned_headline
    ]
    if filtered:
        lead = filtered[0]
        support = filtered[1] if len(filtered) > 1 else None
        return lead, support

    paragraphs = _body_paragraphs(brief_body)
    filtered_paragraphs = [
        paragraph for paragraph in paragraphs if _display_headline(paragraph) != cleaned_headline
    ]
    if not filtered_paragraphs:
        return cleaned_headline, None
    lead = filtered_paragraphs[0]
    support = filtered_paragraphs[1] if len(filtered_paragraphs) > 1 else None
    return lead, support


def _clean_public_body(body: str) -> str:
    lines = body.replace("\r\n", "\n").splitlines()
    kept: list[str] = []
    exclude_section = False

    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("(as of ") or lowered.startswith("as of "):
            continue
        matched = _SECTION_HEADER_RE.match(stripped)
        if matched:
            exclude_section = matched.group("section") in _EXCLUDED_BODY_SECTIONS
            if exclude_section:
                continue

        if exclude_section:
            continue
        if stripped and _is_machine_payload(stripped):
            continue
        kept.append(line.rstrip())

    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _body_paragraphs(body: str) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in body.split("\n\n"):
        normalized = _normalize_public_text(paragraph)
        if not normalized or normalized.startswith("## "):
            continue
        if _SECTION_HEADER_RE.match(normalized):
            continue
        if not _is_public_headline_candidate(normalized):
            continue
        paragraphs.append(normalized)
    return paragraphs


def _normalize_public_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).strip()


def _contains_korean(text: str) -> bool:
    return bool(_HANGUL_RE.search(str(text or "")))


def _is_machine_payload(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if _DICT_LITERAL_RE.match(normalized):
        return True
    return normalized.startswith("{'") or normalized.startswith('{"')


# LLM이 "없음" 같은 무의미 한국어 플레이스홀더를 반환하는 경우를 필터링
_MEANINGLESS_KO: frozenset[str] = frozenset(
    {
        "없음",
        "없음.",
        "없음,",
        "해당없음",
        "해당 없음",
        "해당없음.",
        "해당 없음.",
        "해당없음,",
        "해당 없음,",
        "N/A",
        "n/a",
        "null",
    }
)


def _best_korean_text(*candidates: str) -> str | None:
    for candidate in candidates:
        normalized = _normalize_public_text(candidate)
        if (
            normalized
            and _contains_korean(normalized)
            and not _is_machine_payload(normalized)
            and normalized not in _MEANINGLESS_KO
        ):
            return normalized
    return None


def _data_quality_status(packet: dict[str, Any]) -> str:
    quality = packet.get("data_quality", {})
    if isinstance(quality, dict):
        status = str(quality.get("status", "ok")).strip().lower()
        if status in {"ok", "degraded", "critical"}:
            return status
    return "ok"


def _quality_notes(packet: dict[str, Any]) -> list[str]:
    quality = packet.get("data_quality", {})
    if not isinstance(quality, dict):
        return []
    warnings = quality.get("warnings", [])
    if not isinstance(warnings, list):
        return []
    return [str(item).strip() for item in warnings if str(item).strip()]


def _find_point(points: list[dict[str, Any]], canonical_key: str) -> dict[str, Any] | None:
    for point in points:
        if str(point.get("canonical_key", "")).strip() == canonical_key:
            return point
    return None


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


def _trend_from_point(point: dict[str, Any], canonical_key: str) -> str | None:
    if is_rate_canonical_key(canonical_key):
        change_bps = _change_bps(point)
        if change_bps is None:
            return None
        if change_bps > 0:
            return "up"
        if change_bps < 0:
            return "down"
        return "neutral"

    change_pct = _change_pct(point)
    if change_pct is None:
        return None
    if change_pct > 0:
        return "up"
    if change_pct < 0:
        return "down"
    return "neutral"


def _format_value(canonical_key: str, price: float | None) -> str | None:
    if price is None:
        return None
    if canonical_key == "btc":
        return f"${price:,.0f}"
    if canonical_key == "usdkrw":
        return f"{price:,.2f}"
    if canonical_key in {"nq_futures", "spy"}:
        return f"{price:,.2f}"
    if canonical_key in {"qqq", "soxx"}:
        return f"{price:,.2f}"
    if is_rate_canonical_key(canonical_key):
        return f"{price:.2f}%"
    return f"{price:.2f}"


def _format_change(canonical_key: str, point: dict[str, Any]) -> str | None:
    if is_rate_canonical_key(canonical_key):
        change_bps = _change_bps(point)
        if change_bps is None:
            return None
        sign = "+" if change_bps >= 0 else ""
        return f"{sign}{change_bps:.0f}bp"

    change_pct = _change_pct(point)
    if change_pct is None:
        return None
    sign = "+" if change_pct >= 0 else ""
    return f"{sign}{change_pct:.2f}%"


def _synthetic_history(canonical_key: str, point: dict[str, Any]) -> list[float]:
    price = _resolved_price(point)
    if price is None:
        return []

    if is_rate_canonical_key(canonical_key):
        change_bps = _change_bps(point)
        if change_bps is None:
            return []
        previous = price - (change_bps / 100.0)
        return [round(previous, 4), round(price, 4)]

    change_pct = _change_pct(point)
    if change_pct is None or change_pct <= -100:
        return []
    previous = price / (1 + (change_pct / 100.0))
    return [round(previous, 4), round(price, 4)]


def _market_snapshot_items(packet: dict[str, Any]) -> list[dict[str, Any]]:
    # DEPRECATED: unified-pipeline — use _market_snapshot_items_v2(unified) instead
    packet_sections = {
        "macro": packet.get("macro", []),
        "korea_watch": packet.get("korea_watch", []),
        "us_indices": packet.get("us_indices", []),
    }
    items: list[dict[str, Any]] = []

    for section_name, canonical_key, symbol, label in _PUBLIC_SNAPSHOT_SPECS:
        raw_section = packet_sections.get(section_name, [])
        if not isinstance(raw_section, list):
            continue
        point = _find_point(raw_section, canonical_key)
        if point is None:
            continue
        items.append(
            {
                "symbol": symbol,
                "label": label,
                "value": _format_value(canonical_key, _resolved_price(point)),
                "change": _format_change(canonical_key, point),
                "trend": _trend_from_point(point, canonical_key),
                "isCached": bool(point.get("is_previous_value"))
                or str(point.get("validation_status", "")).strip() == "previous_value",
                "history": _synthetic_history(canonical_key, point),
            }
        )

    btc_spot = packet.get("bitcoin", {}).get("spot", {})
    if isinstance(btc_spot, dict):
        items.append(
            {
                "symbol": "BTC",
                "label": "비트코인 현물",
                "value": _format_value("btc", _resolved_price(btc_spot)),
                "change": _format_change("btc", btc_spot),
                "trend": _trend_from_point(btc_spot, "btc"),
                "isCached": bool(btc_spot.get("is_previous_value"))
                or str(btc_spot.get("validation_status", "")).strip() == "previous_value",
                "history": _synthetic_history("btc", btc_spot),
            }
        )

    if len(items) < _MIN_PUBLIC_TICKER_ITEMS:
        return []
    return items


def _market_snapshot_items_v2(unified: UnifiedOutput) -> list[dict[str, Any]]:
    """Task 6.1 — QuantitativeLayer 소비 전환.

    FC-1, FC-4 포맷은 QuantitativeLayer 생성 시 이미 적용됨. 재포맷 금지.
    """
    quant = unified.quantitative
    ticker_fields = (
        quant.us10y,
        quant.dxy,
        quant.vix,
        quant.usdkrw,
        quant.nq_futures,
        quant.spy,
        quant.qqq,
        quant.soxx,
    )
    items: list[dict[str, Any]] = []
    for ticker in ticker_fields:
        if ticker is None:
            continue
        items.append(
            {
                "symbol": ticker.symbol,
                "label": ticker.label,
                "value": ticker.value_fmt,
                "change": ticker.change,
                "trend": ticker.trend,
                "isCached": ticker.is_cached,
                "history": ticker.sparkline,
            }
        )
    if quant.btc_spot is not None:
        bt = quant.btc_spot
        items.append(
            {
                "symbol": bt.symbol,
                "label": bt.label,
                "value": bt.value_fmt,
                "change": bt.change,
                "trend": bt.trend,
                "isCached": bt.is_cached,
                "history": bt.sparkline,
            }
        )
    if len(items) < _MIN_PUBLIC_TICKER_ITEMS:
        return []
    return items


def _parse_key_metric(raw: str | None) -> str | None:
    """LLM이 Python dict 문자열로 반환한 keyMetric을 읽기 좋은 텍스트로 변환한다.

    예: "{'label': 'Fed Funds Rate', 'value': '3.50%-3.75%', 'change': 'Unchanged'}"
    → "Fed Funds Rate · 3.50%-3.75%"
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("{'") or text.startswith('{"'):
        try:
            d = ast.literal_eval(text)
            if isinstance(d, dict):
                label = str(d.get("label") or d.get("name") or "").strip()
                val = str(d.get("value") or d.get("val") or "").strip()
                change = str(d.get("change") or "").strip()
                parts = [p for p in [label, val] if p]
                if change and change.upper() not in ("N/A", "UNCHANGED", "없음", ""):
                    parts.append(change)
                result = " · ".join(parts)
                return result or None
        except Exception:
            pass
        return None  # 파싱 불가 dict 문자열 — 표시 억제
    return text or None


def _parse_related_stock(entry: str) -> str | None:
    """LLM이 Python dict 문자열로 반환한 종목 항목에서 ticker (+ 등락률)를 추출한다.

    예: "{'ticker': 'NVDA', 'reason': '...', 'change_pct': '-4.8%'}" → "NVDA -4.8%"
    """
    text = entry.strip()
    if not text:
        return None
    if text.startswith("{'") or text.startswith('{"'):
        try:
            d = ast.literal_eval(text)
            if isinstance(d, dict):
                ticker = str(d.get("ticker") or d.get("symbol") or "").strip().upper()
                change_pct = str(d.get("change_pct") or "").strip()
                if not ticker:
                    return None
                if change_pct and change_pct.upper() not in ("N/A", ""):
                    return f"{ticker} {change_pct}"
                return ticker
        except Exception:
            pass
        return None  # 파싱 불가 dict 문자열 — 표시 억제
    return text or None


def _topic_summaries(packet: dict[str, Any]) -> list[dict[str, Any]]:
    raw = packet.get("topic_summaries", {})
    if not isinstance(raw, dict):
        return []

    items: list[dict[str, Any]] = []
    for packet_topic, public_topic, label in _PUBLIC_TOPIC_SPECS:
        entry = raw.get(packet_topic)
        if not isinstance(entry, dict):
            continue
        key_points = entry.get("key_data_points", [])
        notable_stocks = entry.get("notable_stocks", [])
        summary = (
            str(entry.get("market_implication", "")).strip()
            or str(entry.get("summary_text", "")).strip()
        )
        if not summary:
            continue
        items.append(
            {
                "topic": public_topic,
                "label": label,
                "summary": summary,
                "keyMetric": _parse_key_metric(str(key_points[0]).strip())
                if isinstance(key_points, list) and key_points
                else None,
                "relatedStocks": [
                    s for s in (_parse_related_stock(str(item)) for item in notable_stocks) if s
                ]
                if isinstance(notable_stocks, list) and notable_stocks
                else None,
            }
        )
    return items


def _tech_stocks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    stocks = packet.get("tech_stocks", [])
    if not isinstance(stocks, list):
        return []

    results: list[dict[str, Any]] = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        canonical_key = str(stock.get("canonical_key", "")).strip()
        price = _resolved_price(stock)
        change_pct = _change_pct(stock)
        results.append(
            {
                "symbol": str(stock.get("ticker", "")).strip()
                or canonical_key.upper()
                or str(stock.get("label", "")).strip()
                or "TECH",
                "name": str(stock.get("label", "")).strip() or canonical_key.upper() or "기술주",
                "price": f"${price:,.2f}" if price is not None else None,
                "change": _format_change(canonical_key, stock),
                "trend": _trend_from_point(stock, canonical_key),
                "absChangeNum": abs(change_pct) if change_pct is not None else None,
                "isCached": bool(stock.get("is_previous_value"))
                or str(stock.get("validation_status", "")).strip() == "previous_value",
            }
        )
    return results


def _bitcoin_section(packet: dict[str, Any]) -> dict[str, Any]:
    # DEPRECATED: unified-pipeline — use _bitcoin_section_v2(unified) instead
    btc = packet.get("bitcoin", {})
    if not isinstance(btc, dict):
        return {
            "price": None,
            "change": None,
            "trend": None,
            "fearGreedIndex": None,
            "etf": None,
        }

    spot = btc.get("spot", {})
    spot_price = _resolved_price(spot) if isinstance(spot, dict) else None
    snapshots = btc.get("official_etf_snapshots", [])
    issuers: list[dict[str, Any]] = []
    if isinstance(snapshots, list):
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            total_btc = snapshot.get("total_btc")
            aum_usd = snapshot.get("aum_usd")
            issuers.append(
                {
                    "name": str(snapshot.get("ticker", "")).strip()
                    or str(snapshot.get("issuer", "")).strip()
                    or "ETF",
                    "holding": f"{float(total_btc):,.2f} BTC"
                    if isinstance(total_btc, (float, int))
                    else None,
                    "aum": f"${float(aum_usd):,.0f}" if isinstance(aum_usd, (float, int)) else None,
                    "sourceUrl": str(snapshot.get("source_url", "")).strip(),
                }
            )

    total_btc = btc.get("official_etf_total_btc")
    total_aum = btc.get("official_etf_total_aum_usd")
    etf = None
    if issuers or isinstance(total_btc, (float, int)) or isinstance(total_aum, (float, int)):
        etf = {
            "totalHolding": f"{float(total_btc):,.2f} BTC"
            if isinstance(total_btc, (float, int))
            else None,
            "totalAum": f"${float(total_aum):,.0f}"
            if isinstance(total_aum, (float, int))
            else None,
            "issuers": issuers,
        }

    fear_value = btc.get("fear_greed_value")
    fear_label = str(btc.get("fear_greed_label", "")).strip()
    fear_greed = None
    if isinstance(fear_value, int) and fear_label:
        fear_greed = {
            "value": fear_value,
            "label": fear_label,
        }

    return {
        "price": _format_value("btc", spot_price),
        "change": _format_change("btc", spot) if isinstance(spot, dict) else None,
        "trend": _trend_from_point(spot, "btc") if isinstance(spot, dict) else None,
        "fearGreedIndex": fear_greed,
        "etf": etf,
    }


def _bitcoin_section_v2(unified: UnifiedOutput) -> dict[str, Any]:
    """Task 6.2 — QuantitativeLayer.btc 소비 전환.

    FC-2 (btc_total_holding) 포맷은 QuantitativeLayer 생성 시 이미 적용됨.
    개별 issuer 목록은 QuantitativeLayer에 없으므로 빈 목록 사용 (schema compat).
    """
    quant = unified.quantitative
    btc_spot = quant.btc_spot
    etf: dict[str, Any] | None = None
    if (
        quant.btc_total_holding is not None
        or quant.btc_total_aum_usd is not None
        or quant.btc_etf_issuers
    ):
        etf = {
            "totalHolding": quant.btc_total_holding,  # FC-2 이미 적용
            "totalAum": quant.btc_total_aum_usd,
            "issuers": [
                {
                    "name": p.ticker or p.issuer or "ETF",
                    "holding": f"{p.btc_held} BTC" if p.btc_held else None,
                    "aum": p.aum,
                    "sourceUrl": p.source_url,
                }
                for p in quant.btc_etf_issuers
            ],
        }
    fear_greed: dict[str, Any] | None = None
    if quant.btc_fear_greed_value is not None and quant.btc_fear_greed_label is not None:
        fear_greed = {
            "value": quant.btc_fear_greed_value,
            "label": quant.btc_fear_greed_label,
        }
    return {
        "price": btc_spot.value_fmt if btc_spot is not None else None,
        "change": btc_spot.change if btc_spot is not None else None,
        "trend": btc_spot.trend if btc_spot is not None else None,
        "fearGreedIndex": fear_greed,
        "etf": etf,
    }


def _public_news_entries(
    packet: dict[str, Any],
    public_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(public_context, dict):
        items = public_context.get("all_news")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    packet_news = packet.get("news", [])
    if isinstance(packet_news, list):
        return [item for item in packet_news if isinstance(item, dict)]
    return []


def _public_signal_entries(
    packet: dict[str, Any],
    public_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(public_context, dict):
        items = public_context.get("all_x_signals")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    signals = packet.get("x_market_signals", [])
    if isinstance(signals, list):
        return [item for item in signals if isinstance(item, dict)]
    return []


def _source_counts(
    *,
    public_context: dict[str, Any] | None,
    all_news: list[dict[str, Any]],
    all_x_signals: list[dict[str, Any]],
) -> dict[str, int]:
    raw_counts = public_context.get("source_counts") if isinstance(public_context, dict) else None
    if isinstance(raw_counts, dict):
        return {
            "newsCandidates": int(raw_counts.get("newsCandidates", len(all_news)) or 0),
            "newsRanked": int(raw_counts.get("newsRanked", len(all_news)) or 0),
            "newsFeatured": min(len(all_news), _PUBLIC_FEATURED_NEWS_LIMIT),
            "newsAll": len(all_news),
            "xSignalCandidates": int(raw_counts.get("xSignalCandidates", len(all_x_signals)) or 0),
            "xSignalRanked": int(raw_counts.get("xSignalRanked", len(all_x_signals)) or 0),
            "xSignalFeatured": min(len(all_x_signals), _PUBLIC_FEATURED_X_LIMIT),
            "xSignalAll": len(all_x_signals),
        }
    return {
        "newsCandidates": len(all_news),
        "newsRanked": len(all_news),
        "newsFeatured": min(len(all_news), _PUBLIC_FEATURED_NEWS_LIMIT),
        "newsAll": len(all_news),
        "xSignalCandidates": len(all_x_signals),
        "xSignalRanked": len(all_x_signals),
        "xSignalFeatured": min(len(all_x_signals), _PUBLIC_FEATURED_X_LIMIT),
        "xSignalAll": len(all_x_signals),
    }


def _x_signals(
    packet: dict[str, Any],
    run_at: datetime,
    *,
    public_context: dict[str, Any] | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    # DEPRECATED: unified-pipeline — use _x_signals_v2(unified, run_at, limit=...) instead
    signals = _public_signal_entries(packet, public_context)[:limit]
    if not isinstance(signals, list) or not signals:
        return []

    results: list[dict[str, Any]] = []
    for index, signal in enumerate(signals, start=1):
        if not isinstance(signal, dict):
            continue
        content = str(signal.get("summary", "")).strip() or str(signal.get("headline", "")).strip()
        impact = str(signal.get("why_it_matters", "")).strip() or content
        if not content or not impact:
            continue
        sentiment = str(signal.get("sentiment", "neutral")).strip().lower()
        if sentiment not in {"bullish", "bearish", "neutral"}:
            sentiment = "neutral"
        posted_at = str(signal.get("posted_at", "")).strip() or run_at.isoformat()
        raw_content = content if not _contains_korean(content) else None
        content_ko = (
            _best_korean_text(
                str(signal.get("summary", "")).strip(),
                str(signal.get("headline", "")).strip(),
                str(signal.get("why_it_matters", "")).strip(),
            )
            or content
        )
        impact_ko = (
            _best_korean_text(
                str(signal.get("why_it_matters", "")).strip(),
                str(signal.get("summary", "")).strip(),
            )
            or impact
        )
        results.append(
            {
                "id": f"x-{index}",
                "postedAt": posted_at,
                "impact": impact_ko,
                "sentiment": sentiment,
                "content": content_ko,
                "rawContent": raw_content,
            }
        )
    return results


def _news_items(
    packet: dict[str, Any],
    run_at: datetime,
    *,
    public_context: dict[str, Any] | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    # DEPRECATED: unified-pipeline — use _news_items_v2(unified, run_at, limit=...) instead
    normalized_packet_news = _public_news_entries(packet, public_context)[:limit]
    fallback_items: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_packet_news, start=1):
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        if not url or not title:
            continue
        topic = _normalize_news_topic(item.get("topic"))
        summary_ko = _best_korean_text(
            str(item.get("summary_ko", "")).strip(),
            str(item.get("summary", "")).strip(),
            str(item.get("why_it_matters", "")).strip(),
        )
        interpretation_ko = _best_korean_text(
            str(item.get("interpretation_ko", "")).strip(),
            str(item.get("why_it_matters", "")).strip(),
            str(item.get("summary", "")).strip(),
        )
        fallback_items.append(
            {
                "id": f"news-{index}",
                "publishedAt": str(item.get("published_at", "")).strip() or run_at.isoformat(),
                "category": topic,
                "title": title,
                "interpretation": interpretation_ko,
                "summaryKo": summary_ko,
                "rawTitle": title if not _contains_korean(title) else None,
                "source": str(item.get("source", "")).strip() or _source_from_url(url),
                "sourceTier": "tier1" if _source_tier_value(item) == 1 else "standard",
                "url": url,
                "urgency": "high" if _source_tier_value(item) == 1 else "medium",
                "tags": [_topic_label(topic)],
            }
        )
    return fallback_items


def _x_signals_v2(
    unified: UnifiedOutput,
    run_at: datetime,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Task 7.2 — NarrativeLayer.x_signals 소비 전환."""
    signals = unified.narrative.x_signals[:limit]
    if not signals:
        return []

    results: list[dict[str, Any]] = []
    for index, signal in enumerate(signals, start=1):
        if not isinstance(signal, dict):
            continue
        content = str(signal.get("summary", "")).strip() or str(signal.get("headline", "")).strip()
        impact = str(signal.get("why_it_matters", "")).strip() or content
        if not content or not impact:
            continue
        sentiment = str(signal.get("sentiment", "neutral")).strip().lower()
        if sentiment not in {"bullish", "bearish", "neutral"}:
            sentiment = "neutral"
        posted_at = str(signal.get("posted_at", "")).strip() or run_at.isoformat()
        raw_content = content if not _contains_korean(content) else None
        content_ko = (
            _best_korean_text(
                str(signal.get("summary", "")).strip(),
                str(signal.get("headline", "")).strip(),
                str(signal.get("why_it_matters", "")).strip(),
            )
            or content
        )
        impact_ko = (
            _best_korean_text(
                str(signal.get("why_it_matters", "")).strip(),
                str(signal.get("summary", "")).strip(),
            )
            or impact
        )
        results.append(
            {
                "id": f"x-{index}",
                "postedAt": posted_at,
                "impact": impact_ko,
                "sentiment": sentiment,
                "content": content_ko,
                "rawContent": raw_content,
            }
        )
    return results


def _news_items_v2(
    unified: UnifiedOutput,
    run_at: datetime,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Task 7.1 — NarrativeLayer.news 소비 전환."""
    raw_news = unified.narrative.news[:limit]
    results: list[dict[str, Any]] = []
    for index, item in enumerate(raw_news, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        if not url or not title:
            continue
        topic = _normalize_news_topic(item.get("topic"))
        summary_ko = _best_korean_text(
            str(item.get("summary_ko", "")).strip(),
            str(item.get("summary", "")).strip(),
            str(item.get("why_it_matters", "")).strip(),
        )
        interpretation_ko = _best_korean_text(
            str(item.get("interpretation_ko", "")).strip(),
            str(item.get("why_it_matters", "")).strip(),
            str(item.get("summary", "")).strip(),
        )
        results.append(
            {
                "id": f"news-{index}",
                "publishedAt": str(item.get("published_at", "")).strip() or run_at.isoformat(),
                "category": topic,
                "title": title,
                "interpretation": interpretation_ko,
                "summaryKo": summary_ko,
                "rawTitle": title if not _contains_korean(title) else None,
                "source": str(item.get("source", "")).strip() or _source_from_url(url),
                "sourceTier": "tier1" if _source_tier_value(item) == 1 else "standard",
                "url": url,
                "urgency": "high" if _source_tier_value(item) == 1 else "medium",
                "tags": [_topic_label(topic)],
            }
        )
    return results


def _filter_public_news_for_display(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        title = _best_korean_text(str(item.get("title", "")).strip())
        if not title:
            continue
        summary_ko = _best_korean_text(str(item.get("summaryKo", "")).strip())
        interpretation = _best_korean_text(
            str(item.get("interpretation", "")).strip(),
        )
        if not summary_ko or not interpretation:
            continue
        item["title"] = title
        item["summaryKo"] = summary_ko
        item["interpretation"] = interpretation
        filtered.append(item)
    return filtered


def _filter_public_signals_for_display(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        content = _best_korean_text(str(item.get("content", "")).strip())
        if not content:
            continue
        impact = _best_korean_text(str(item.get("impact", "")).strip(), content) or content
        item["content"] = content
        item["impact"] = impact
        filtered.append(item)
    return filtered


def _translation_key(text: str) -> str:
    normalized = _normalize_public_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _needs_translation(text: str | None) -> bool:
    normalized = _normalize_public_text(text or "")
    return (
        bool(normalized)
        and not _contains_korean(normalized)
        and not _is_machine_payload(normalized)
    )


def _translation_cache_path(settings: Settings) -> Path:
    return settings.cache_dir / _TRANSLATION_CACHE_FILE


def _load_translation_cache(settings: Settings) -> dict[str, str]:
    path = _translation_cache_path(settings)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in payload.items()
        if str(key).strip() and str(value).strip()
    }


def _save_translation_cache(settings: Settings, cache_map: dict[str, str]) -> None:
    path = _translation_cache_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache_map, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_public_translation(
    *,
    headline: str,
    summary_lead: str,
    summary_support: str | None,
    topic_summaries: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
    x_signals: list[dict[str, Any]],
    settings: Settings | None,
    observer: PipelineObserver | None,
) -> tuple[str, str, str | None, str]:
    if settings is None:
        return headline, summary_lead, summary_support, "ok"

    translation_map, status = _translate_public_texts(
        headline=headline,
        summary_lead=summary_lead,
        summary_support=summary_support,
        topic_summaries=topic_summaries,
        news_items=news_items,
        x_signals=x_signals,
        settings=settings,
        observer=observer,
    )
    translated_headline = translation_map.get(_translation_key(headline), headline)
    translated_lead = translation_map.get(_translation_key(summary_lead), summary_lead)
    translated_support = (
        translation_map.get(_translation_key(summary_support), summary_support)
        if summary_support
        else None
    )
    if not translation_map:
        return translated_headline, translated_lead, translated_support, status

    for item in topic_summaries:
        summary = str(item.get("summary", "")).strip()
        translated = translation_map.get(_translation_key(summary))
        if translated:
            item["summary"] = translated

    for item in news_items:
        title = str(item.get("title", "")).strip()
        interpretation = str(item.get("interpretation", "")).strip()
        summary_ko = str(item.get("summaryKo", "")).strip()
        translated_title = translation_map.get(_translation_key(title))
        translated_interpretation = translation_map.get(_translation_key(interpretation))
        translated_summary = translation_map.get(_translation_key(summary_ko))

        if translated_title:
            if not item.get("rawTitle") and title and title != translated_title:
                item["rawTitle"] = title
            item["title"] = translated_title
        if translated_summary:
            item["summaryKo"] = translated_summary
        if translated_interpretation:
            item["interpretation"] = translated_interpretation
        elif translated_summary and not interpretation:
            item["interpretation"] = translated_summary

    for item in x_signals:
        content = str(item.get("content", "")).strip()
        impact = str(item.get("impact", "")).strip()
        translated_content = translation_map.get(_translation_key(content))
        translated_impact = translation_map.get(_translation_key(impact))
        if translated_content:
            if not item.get("rawContent") and content and content != translated_content:
                item["rawContent"] = content
            item["content"] = translated_content
        if translated_impact:
            item["impact"] = translated_impact

    return translated_headline, translated_lead, translated_support, status


def _translate_public_texts(
    *,
    headline: str,
    summary_lead: str,
    summary_support: str | None,
    topic_summaries: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
    x_signals: list[dict[str, Any]],
    settings: Settings,
    observer: PipelineObserver | None,
) -> tuple[dict[str, str], str]:
    cache_map = _load_translation_cache(settings)
    priority_texts: dict[str, str] = {}
    secondary_texts: dict[str, str] = {}

    for candidate in (headline, summary_lead, summary_support or ""):
        normalized = _normalize_public_text(candidate)
        if _needs_translation(normalized):
            priority_texts[_translation_key(normalized)] = normalized

    for item in topic_summaries:
        summary = _normalize_public_text(str(item.get("summary", "")).strip())
        if _needs_translation(summary):
            secondary_texts[_translation_key(summary)] = summary

    for item in news_items:
        for field in ("title", "summaryKo", "interpretation"):
            value = _normalize_public_text(str(item.get(field, "")).strip())
            if _needs_translation(value):
                priority_texts[_translation_key(value)] = value

    for item in x_signals:
        for field in ("content", "impact"):
            value = _normalize_public_text(str(item.get(field, "")).strip())
            if _needs_translation(value):
                priority_texts[_translation_key(value)] = value

    translatable_texts = {**priority_texts, **secondary_texts}

    if not translatable_texts:
        return cache_map, "ok"

    pending_priority = {
        key: text
        for key, text in priority_texts.items()
        if not _normalize_public_text(cache_map.get(key, ""))
    }
    pending_secondary = {
        key: text
        for key, text in secondary_texts.items()
        if not _normalize_public_text(cache_map.get(key, ""))
    }
    pending = {**pending_priority, **pending_secondary}
    if not pending:
        return cache_map, "ok"

    if not pending_priority and len(pending_secondary) < 2:
        if observer is not None:
            observer.log_event(
                "public_translation_skipped",
                reason="low_value_pending",
                pending_priority=0,
                pending_secondary=len(pending_secondary),
            )
        return cache_map, "ok"

    if not settings.openai_api_key:
        return cache_map, "failed"

    client = OpenAI(api_key=settings.openai_api_key)
    translated_count = 0
    batch_failed = False

    for items in _translation_batches(pending):
        try:
            response = client.responses.create(
                model=settings.openai_public_translation_model,
                instructions=(
                    "시장 브리프 공개 JSON용 번역기입니다. 입력 문장을 자연스러운 한국어로만 옮기세요. "
                    "숫자, 티커, ETF 이름, URL, 출처명은 보존하세요. 장황하게 늘리지 말고 한두 문장 안에서 끝내세요."
                ),
                input=json.dumps({"items": items}, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "public_translation_batch",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "items": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "translated": {"type": "string"},
                                        },
                                        "required": ["id", "translated"],
                                        "additionalProperties": False,
                                    },
                                }
                            },
                            "required": ["items"],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    }
                },
                reasoning={"effort": "minimal"},
                max_output_tokens=min(2400, max(900, 220 * len(items))),
            )
        except Exception as exc:
            batch_failed = True
            if observer is not None:
                observer.log_event(
                    "public_translation_failed",
                    level=logging.WARNING,
                    message="공개 JSON 번역 중 오류가 있어 원문을 유지할게요.",
                    reason=str(exc),
                    error_type=type(exc).__name__,
                    batch_size=len(items),
                )
            else:
                log_structured(
                    logger,
                    event="error.raised",
                    message="공개 JSON 번역 중 오류가 있어 원문을 유지할게요.",
                    level=logging.WARNING,
                    phase="public_translation",
                    reason=str(exc),
                    error_type=type(exc).__name__,
                    batch_size=len(items),
                )
            continue

        if observer is not None:
            observer.record_provider_usage(
                "openai",
                phase="public_translation",
                requests=1,
                **usage_snapshot(response),
            )

        try:
            payload = json.loads((response.output_text or "").strip())
        except json.JSONDecodeError:
            batch_failed = True
            if observer is not None:
                observer.log_event(
                    "public_translation_failed",
                    level=logging.WARNING,
                    message="공개 JSON 번역 응답이 JSON 형식을 만족하지 않아 원문을 유지할게요.",
                    reason="invalid_json",
                    preview=(response.output_text or "")[:200],
                    batch_size=len(items),
                )
            continue

        translated_items = payload.get("items", []) if isinstance(payload, dict) else []
        for item in translated_items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id", "")).strip()
            translated = _normalize_public_text(str(item.get("translated", "")).strip())
            if not key or not translated:
                continue
            cache_map[key] = translated
            translated_count += 1

    _save_translation_cache(settings, cache_map)

    if translated_count == len(pending):
        return cache_map, "ok"
    if translated_count > 0 or batch_failed:
        return cache_map, "partial"
    return cache_map, "failed"


def _translation_batches(pending: dict[str, str]) -> list[list[dict[str, str]]]:
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_chars = 0

    for key, text in pending.items():
        item = {"id": key, "text": text}
        item_chars = len(text)
        if current and (
            len(current) >= _PUBLIC_TRANSLATION_BATCH_ITEMS
            or current_chars + item_chars > _PUBLIC_TRANSLATION_BATCH_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars

    if current:
        batches.append(current)

    return batches


def _normalize_news_topic(raw_topic: Any) -> str:
    normalized = str(raw_topic or "").strip().lower()
    return _PUBLIC_NEWS_TOPIC_MAP.get(normalized, "us-stocks")


def _topic_label(topic: str) -> str:
    return {
        "macro": "거시경제",
        "bigtech": "빅테크",
        "bitcoin": "비트코인",
        "us-stocks": "미국증시",
    }.get(topic, "시장")


def _source_tier_value(item: dict[str, Any]) -> int:
    raw = item.get("source_tier")
    if isinstance(raw, int):
        return raw
    normalized = str(raw or "").strip().lower()
    if normalized in {"1", "tier1", "tier_1"}:
        return 1
    return 0


def _source_from_url(url: str) -> str:
    hostname = urlparse(url).netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or "Unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_local_dates(brief_dir: Path) -> list[str]:
    if not brief_dir.exists():
        return []
    dates = [path.stem for path in brief_dir.glob("*.json") if path.is_file() and path.stem.strip()]
    return sorted(set(dates), reverse=True)


class _PublicR2Client:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            CacheControl="public, max-age=300",
        )

    def list_dates(self) -> list[str]:
        continuation_token: str | None = None
        dates: set[str] = set()
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": "briefs/",
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = str(item.get("Key", "")).strip()
                if key.startswith("briefs/") and key.endswith(".json"):
                    dates.add(Path(key).stem)
            if not response.get("IsTruncated"):
                break
            continuation_token = str(response.get("NextContinuationToken") or "").strip() or None
        return sorted(dates, reverse=True)


def _public_r2_client(settings: Settings) -> _PublicR2Client | None:
    if not all(
        [
            settings.r2_public_bucket,
            settings.r2_s3_endpoint,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
        ]
    ):
        return None
    return _PublicR2Client(
        bucket=settings.r2_public_bucket,
        endpoint=settings.r2_s3_endpoint,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
    )
