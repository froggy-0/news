from __future__ import annotations

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.market import build_market_packet
from morning_brief.data.news import build_news_packet
from morning_brief.emailer import GmailSender

logger = logging.getLogger(__name__)


def _safe_price(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _assess_data_quality(packet: dict, news_packet: list[dict]) -> dict:
    macro = packet.get("macro", [])
    us_indices = packet.get("us_indices", [])
    tech_stocks = packet.get("tech_stocks", [])
    btc = packet.get("bitcoin", {})

    numeric_points = macro + us_indices + tech_stocks + btc.get("etf_points", []) + [btc.get("spot", {})]
    zero_points = [
        p for p in numeric_points if isinstance(p, dict) and _safe_price(p.get("price", 0.0)) <= 0.0
    ]

    zero_ratio = (len(zero_points) / len(numeric_points)) if numeric_points else 1.0
    news_count = len(news_packet)
    preferred_news_count = sum(
        1 for item in news_packet if isinstance(item, dict) and bool(item.get("preferred_source"))
    )
    tier_1_news_count = sum(
        1
        for item in news_packet
        if isinstance(item, dict) and str(item.get("source_tier", "")).lower() == "tier_1"
    )
    unique_news_domains = len(
        {
            str(item.get("domain", "")).strip().lower()
            for item in news_packet
            if isinstance(item, dict) and str(item.get("domain", "")).strip()
        }
    )
    fresh_news_count = sum(
        1
        for item in news_packet
        if isinstance(item, dict)
        and item.get("age_hours") is not None
        and _safe_price(item.get("age_hours", 10_000)) <= 24.0
    )

    warnings: list[str] = []
    if zero_ratio >= 0.6:
        warnings.append(f"가격 데이터의 {zero_ratio*100:.0f}%가 폴백 값입니다")
    if news_count < 3:
        warnings.append(f"핵심 뉴스가 {news_count}건으로 최소 기준(3건) 미달입니다")
    if news_count >= 3 and preferred_news_count < 2:
        warnings.append(
            f"우선 신뢰 출처 뉴스가 {preferred_news_count}건으로 충분하지 않습니다"
        )
    if news_count >= 3 and tier_1_news_count < 1:
        warnings.append("최상위 신뢰 출처(Reuters/Bloomberg/WSJ/FT) 기사가 없습니다")
    if news_count >= 3 and unique_news_domains < 3:
        warnings.append(
            f"뉴스 출처 다양성이 낮습니다({unique_news_domains}개 도메인)"
        )
    if news_count >= 3 and fresh_news_count < 2:
        warnings.append(f"24시간 내 최신 뉴스가 {fresh_news_count}건으로 부족합니다")

    if news_count < 3 or zero_ratio >= 0.8:
        status = "critical"
    elif warnings:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "zero_price_ratio": round(zero_ratio, 4),
        "news_count": news_count,
        "preferred_news_count": preferred_news_count,
        "tier_1_news_count": tier_1_news_count,
        "unique_news_domains": unique_news_domains,
        "fresh_news_count": fresh_news_count,
        "warnings": warnings,
    }



def run_pipeline(settings: Settings) -> str:
    logger.info("Pipeline started")
    market_packet = build_market_packet(
        fred_api_key=settings.fred_api_key,
        alpha_vantage_api_key=settings.alpha_vantage_api_key,
        cache_dir=settings.cache_dir,
    )
    news_packet = build_news_packet(
        max_items=settings.max_news_items,
        newsapi_key=settings.newsapi_key,
    )
    logger.info("Collected market points and %s news item(s)", len(news_packet))

    packet = {
        **market_packet,
        "news": news_packet,
    }
    quality = _assess_data_quality(packet=packet, news_packet=news_packet)
    packet["data_quality"] = quality
    if quality["status"] != "ok":
        logger.warning("Data quality status: %s | %s", quality["status"], "; ".join(quality["warnings"]))

    briefing = generate_briefing(packet=packet, settings=settings)

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(settings.timezone))
    file_name = now.strftime("brief_%Y%m%d_%H%M.md")
    output_path = settings.output_dir / file_name
    output_path.write_text(briefing, encoding="utf-8")
    logger.info("Briefing saved: %s", output_path)

    subject = f"좋은 아침이에요 | 미국 기술주·비트코인 브리핑 ({now.strftime('%Y-%m-%d')})"
    GmailSender(settings).send(subject=subject, body=briefing)
    logger.info("Pipeline completed")

    return briefing
