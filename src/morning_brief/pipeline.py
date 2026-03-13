from __future__ import annotations

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.data_quality import assess_data_quality
from morning_brief.data.market import build_market_packet
from morning_brief.data.news import build_news_packet
from morning_brief.data.sources.provider_runtime import (
    provider_stats_snapshot,
    reset_provider_runtime_state,
)
from morning_brief.emailer import GmailSender
from morning_brief.research_backfill import backfill_news_with_web_search

logger = logging.getLogger(__name__)

_assess_data_quality = assess_data_quality



def run_pipeline(settings: Settings) -> str:
    reset_provider_runtime_state()
    logger.info("브리핑 파이프라인을 시작할게요.")
    market_packet = build_market_packet(
        fred_api_key=settings.fred_api_key,
        alpha_vantage_api_key=settings.alpha_vantage_api_key,
        cache_dir=settings.cache_dir,
    )
    news_packet = build_news_packet(settings=settings)
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

    subject = f"미국 기술주·비트코인 시장 브리핑 ({now.strftime('%Y-%m-%d')})"
    GmailSender(settings).send(subject=subject, body=briefing)
    provider_stats = provider_stats_snapshot()
    if provider_stats:
        logger.info("이번 실행의 수집 공급자 상태는 %s", provider_stats)
    logger.info("브리핑 파이프라인을 마쳤어요.")

    return briefing
