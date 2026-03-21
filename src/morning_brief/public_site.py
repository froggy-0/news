from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from morning_brief.brief_formatting import extract_sections, parse_news_items
from morning_brief.config import Settings
from morning_brief.data.market_policy import is_rate_canonical_key
from morning_brief.observability import PipelineObserver

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
) -> _PublicBriefArtifacts:
    run_local = run_at.astimezone(ZoneInfo(settings.timezone))
    date_key = run_local.strftime("%Y-%m-%d")
    brief_relative_path = f"briefs/{date_key}.json"
    public_dir = settings.output_dir / "public"

    brief_payload = build_public_brief(
        packet=packet,
        briefing=briefing,
        run_at=run_local,
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
) -> dict[str, Any]:
    section_map = extract_sections(briefing)
    brief_body = _brief_body_without_title(briefing)

    return {
        "meta": {
            "date": run_at.strftime("%Y-%m-%d"),
            "generatedAt": run_at.isoformat(),
            "dataQuality": _data_quality_status(packet),
            "qualityNotes": _quality_notes(packet),
        },
        "marketSnapshot": {
            "items": _market_snapshot_items(packet),
        },
        "aiJudgment": {
            "headline": _headline_from_sections(section_map, brief_body),
            "body": brief_body,
        },
        "topicSummaries": _topic_summaries(packet),
        "techStocks": _tech_stocks(packet),
        "bitcoin": _bitcoin_section(packet),
        "xSignals": _x_signals(packet, run_at),
        "news": _news_items(packet, section_map.get("section_4_2", ""), run_at),
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
        candidate = line.strip()
        if candidate:
            return candidate
    for paragraph in brief_body.split("\n\n"):
        candidate = paragraph.strip()
        if candidate and not candidate.startswith("## "):
            return candidate
    return "오늘 브리핑을 준비했어요."


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
    if isinstance(resolved, (float, int)):
        return float(resolved)
    price = point.get("price")
    if isinstance(price, (float, int)):
        return float(price)
    return None


def _change_pct(point: dict[str, Any]) -> float | None:
    raw = point.get("change_pct")
    if isinstance(raw, (float, int)):
        return float(raw)
    return None


def _change_bps(point: dict[str, Any]) -> float | None:
    raw = point.get("change_bps")
    if isinstance(raw, (float, int)):
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

    return items


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
                "keyMetric": str(key_points[0]).strip()
                if isinstance(key_points, list) and key_points
                else None,
                "relatedStocks": [str(item).strip() for item in notable_stocks if str(item).strip()]
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


def _x_signals(packet: dict[str, Any], run_at: datetime) -> list[dict[str, Any]] | None:
    signals = packet.get("x_market_signals", [])
    if not isinstance(signals, list) or not signals:
        return None

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
        results.append(
            {
                "id": f"x-{index}",
                "postedAt": posted_at,
                "impact": impact,
                "sentiment": sentiment,
                "content": content,
            }
        )
    return results or None


def _news_items(packet: dict[str, Any], section_4_2: str, run_at: datetime) -> list[dict[str, Any]]:
    packet_news = packet.get("news", [])
    normalized_packet_news = (
        [item for item in packet_news if isinstance(item, dict)]
        if isinstance(packet_news, list)
        else []
    )
    parsed_news = parse_news_items(section_4_2)
    if parsed_news:
        results = [
            _news_item_from_brief(parsed, normalized_packet_news, index, run_at)
            for index, parsed in enumerate(parsed_news, start=1)
        ]
        valid_results = [item for item in results if item is not None]
        if valid_results:
            return valid_results

    fallback_items: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_packet_news[:5], start=1):
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        if not url or not title:
            continue
        topic = _normalize_news_topic(item.get("topic"))
        fallback_items.append(
            {
                "id": f"news-{index}",
                "publishedAt": str(item.get("published_at", "")).strip() or run_at.isoformat(),
                "category": topic,
                "title": title,
                "interpretation": str(item.get("why_it_matters", "")).strip()
                or str(item.get("summary", "")).strip()
                or None,
                "source": str(item.get("source", "")).strip() or _source_from_url(url),
                "sourceTier": "tier1" if _source_tier_value(item) == 1 else "standard",
                "url": url,
                "urgency": "high" if _source_tier_value(item) == 1 else "medium",
                "tags": [_topic_label(topic)],
            }
        )
    return fallback_items


def _news_item_from_brief(
    parsed: dict[str, Any],
    packet_news: list[dict[str, Any]],
    index: int,
    run_at: datetime,
) -> dict[str, Any] | None:
    url = str(parsed.get("source_url") or "").strip()
    headline = str(parsed.get("headline") or "").strip()
    if not headline:
        return None

    matched = _match_packet_news(parsed, packet_news)
    matched_url = str(matched.get("url", "")).strip() if matched else ""
    final_url = url or matched_url
    if not final_url:
        return None

    topic = _normalize_news_topic(matched.get("topic") if matched else None)
    interpretation = str(parsed.get("tldr") or "").strip()
    if not interpretation and matched:
        interpretation = (
            str(matched.get("why_it_matters", "")).strip()
            or str(matched.get("summary", "")).strip()
        )

    source_name = str(parsed.get("source_name") or "").strip()
    if not source_name and matched:
        source_name = str(matched.get("source", "")).strip()
    if not source_name:
        source_name = _source_from_url(final_url)

    source_tier = "standard"
    urgency = "medium"
    if matched and _source_tier_value(matched) == 1:
        source_tier = "tier1"
        urgency = "high"

    published_at = (
        str(matched.get("published_at", "")).strip() if matched is not None else ""
    ) or run_at.isoformat()

    return {
        "id": f"news-{index}",
        "publishedAt": published_at,
        "category": topic,
        "title": headline,
        "interpretation": interpretation or None,
        "source": source_name,
        "sourceTier": source_tier,
        "url": final_url,
        "urgency": urgency,
        "tags": [_topic_label(topic)],
    }


def _match_packet_news(
    parsed: dict[str, Any], packet_news: list[dict[str, Any]]
) -> dict[str, Any] | None:
    parsed_url = str(parsed.get("source_url") or "").strip()
    parsed_headline = str(parsed.get("headline") or "").strip().lower()
    if parsed_url:
        for item in packet_news:
            if str(item.get("url", "")).strip() == parsed_url:
                return item
    for item in packet_news:
        title = str(item.get("title", "")).strip().lower()
        if parsed_headline and title == parsed_headline:
            return item
    for item in packet_news:
        title = str(item.get("title", "")).strip().lower()
        if parsed_headline and parsed_headline in title:
            return item
    return None


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
