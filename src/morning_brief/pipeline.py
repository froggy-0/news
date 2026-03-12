from __future__ import annotations

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.market import build_market_packet
from morning_brief.data.news import build_news_packet, summarize_news_packet_quality
from morning_brief.emailer import GmailSender
from morning_brief.research_backfill import backfill_news_with_web_search

logger = logging.getLogger(__name__)

MIN_NEWS_ITEMS = 3
MIN_PREFERRED_NEWS_ITEMS = 2
MIN_TIER_1_NEWS_ITEMS = 1
MIN_UNIQUE_NEWS_DOMAINS = 3
MIN_FRESH_NEWS_ITEMS = 2


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
    news_quality = summarize_news_packet_quality(news_packet)
    news_count = news_quality["count"]
    preferred_news_count = news_quality["preferred_count"]
    tier_1_news_count = news_quality["tier_1_count"]
    unique_news_domains = news_quality["unique_domains"]
    fresh_news_count = news_quality["fresh_count"]

    warnings: list[str] = []
    if zero_ratio >= 0.6:
        warnings.append(f"가격 데이터의 {zero_ratio*100:.0f}%가 폴백 값입니다")
    if news_count < MIN_NEWS_ITEMS:
        warnings.append(
            f"핵심 뉴스가 {news_count}건으로 최소 기준({MIN_NEWS_ITEMS}건) 미달입니다"
        )
    if news_count >= MIN_NEWS_ITEMS and preferred_news_count < MIN_PREFERRED_NEWS_ITEMS:
        warnings.append(
            f"우선 신뢰 출처 뉴스가 {preferred_news_count}건으로 충분하지 않습니다"
        )
    if news_count >= MIN_NEWS_ITEMS and tier_1_news_count < MIN_TIER_1_NEWS_ITEMS:
        warnings.append("최상위 신뢰 출처(Reuters/Bloomberg/WSJ/FT) 기사가 없습니다")
    if news_count >= MIN_NEWS_ITEMS and unique_news_domains < MIN_UNIQUE_NEWS_DOMAINS:
        warnings.append(
            f"뉴스 출처 다양성이 낮습니다({unique_news_domains}개 도메인)"
        )
    if news_count >= MIN_NEWS_ITEMS and fresh_news_count < MIN_FRESH_NEWS_ITEMS:
        warnings.append(f"24시간 내 최신 뉴스가 {fresh_news_count}건으로 부족합니다")

    if news_count < MIN_NEWS_ITEMS or zero_ratio >= 0.8:
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
    logger.info("브리핑 파이프라인을 시작할게요.")
    market_packet = build_market_packet(
        fred_api_key=settings.fred_api_key,
        alpha_vantage_api_key=settings.alpha_vantage_api_key,
        cache_dir=settings.cache_dir,
    )
    news_packet = build_news_packet(
        max_items=settings.max_news_items,
        newsapi_key=settings.newsapi_key,
    )
    logger.info("시장 지표와 뉴스 %s건을 모았어요.", len(news_packet))

    packet = {
        **market_packet,
        "news": news_packet,
    }
    quality = _assess_data_quality(packet=packet, news_packet=news_packet)
    if quality["status"] != "ok":
        enriched_news, web_search_references = backfill_news_with_web_search(
            packet=packet,
            quality=quality,
            settings=settings,
        )
        if enriched_news != news_packet:
            news_packet = enriched_news
            packet["news"] = news_packet
            quality = _assess_data_quality(packet=packet, news_packet=news_packet)
            logger.info(
                "웹 검색으로 보강한 뒤 데이터 품질을 다시 확인했어요: %s",
                quality["status"],
            )
        if web_search_references:
            packet["web_search_references"] = web_search_references

    packet["data_quality"] = quality
    if quality["status"] != "ok":
        logger.warning(
            "데이터 품질 상태는 %s예요. 확인할 점은 %s",
            quality["status"],
            "; ".join(quality["warnings"]),
        )

    briefing = generate_briefing(packet=packet, settings=settings)

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(settings.timezone))
    file_name = now.strftime("brief_%Y%m%d_%H%M.md")
    output_path = settings.output_dir / file_name
    output_path.write_text(briefing, encoding="utf-8")
    logger.info("브리핑을 저장했어요: %s", output_path)

    subject = f"미국 기술주·비트코인 브리핑 ({now.strftime('%Y-%m-%d')})"
    GmailSender(settings).send(subject=subject, body=briefing)
    logger.info("브리핑 파이프라인을 마쳤어요.")

    return briefing
