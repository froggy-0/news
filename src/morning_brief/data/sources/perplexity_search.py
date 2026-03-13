from __future__ import annotations

import logging

from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)


def fetch_news_from_perplexity(*, max_items: int, api_key: str) -> list[NewsItem]:
    if not api_key:
        logger.info("Perplexity API 키가 아직 없어 legacy 뉴스 수집으로 이어갈게요.")
        return []

    logger.info(
        "Perplexity 뉴스 provider 인터페이스만 먼저 연결해 두었어요. "
        "다음 단계에서 실제 검색 호출을 붙일게요. 지금은 legacy 뉴스 수집으로 이어갈게요."
    )
    return []
