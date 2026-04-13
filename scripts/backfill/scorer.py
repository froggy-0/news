"""FinBERT 스코어러 및 날짜별 집계기.

기존 finbert_sentiment.py의 FinBertScorer / build_news_sentiment_text를
직접 import하여 재사용한다. 모델 가중치는 스크립트 전체에서 단 한 번 로딩.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal

try:
    from morning_brief.data.finbert_sentiment import (
        FinBertScorer,
        SentimentResult,
        build_news_sentiment_text,
    )
except ImportError as exc:
    raise ImportError(
        "FinBERT 의존성 미설치. 아래 명령어로 설치하세요:\n  pip install -r requirements-ml.txt"
    ) from exc

from backfill.sources.coindesk import RawArticle

logger = logging.getLogger(__name__)


@dataclass
class _BackfillFinBertSettings:
    """FinBertScorer 생성자에 필요한 최소 설정 (duck typing 호환)."""

    finbert_model: str = "ProsusAI/finbert"
    finbert_model_path: str = ""
    finbert_model_revision: str = ""
    finbert_batch_size: int = 32
    finbert_bullish_threshold: float = 0.3
    finbert_bearish_threshold: float = -0.3


@dataclass
class DailyAggregate:
    """날짜별 FinBERT 집계 결과.

    std: count < 2이면 None (numpy.std([x], ddof=1) = NaN → None 변환).
    coindesk_count / alpaca_count: dedup 이전 원본 기사 수 (리포트용).
    """

    date: str  # YYYY-MM-DD (UTC 기준)
    mean: float | None  # 유효 score 평균, count=0이면 None
    std: float | None  # 유효 score 표준편차 (ddof=1), count<2이면 None
    count: int  # 유효 score 기사 수 (score=None 제외)
    status: Literal["ok", "degraded", "skipped"]
    coindesk_count: int  # 소스별 기사 수 (리포트용)
    alpaca_count: int


def _determine_status(count: int) -> Literal["ok", "degraded", "skipped"]:
    if count >= 5:
        return "ok"
    if count >= 2:
        return "degraded"
    return "skipped"


def score_and_aggregate(
    articles_by_date: dict[str, list[RawArticle]],
    *,
    batch_size: int = 32,
) -> list[DailyAggregate]:
    """전체 기사를 일괄 배치 추론 후 날짜별 DailyAggregate 리스트 반환.

    처리 순서:
    1. FinBertScorer 단 한 번 초기화 (루프 바깥)
    2. 모든 날짜의 기사를 flat list로 합산
    3. build_news_sentiment_text()로 텍스트 변환
    4. scorer.score_texts()로 일괄 추론
    5. 날짜별 집계
    """
    if not articles_by_date:
        return []

    settings = _BackfillFinBertSettings(finbert_batch_size=batch_size)
    scorer = FinBertScorer(settings)  # 단 한 번 생성

    # flat list 구성 (순서 보존을 위해 sorted dates 사용)
    all_articles: list[RawArticle] = []
    date_ranges: dict[str, tuple[int, int]] = {}  # date → (start_idx, end_idx)

    for date in sorted(articles_by_date.keys()):
        articles = articles_by_date[date]
        start = len(all_articles)
        all_articles.extend(articles)
        date_ranges[date] = (start, len(all_articles))

    # 텍스트 변환: RawArticle → dict → build_news_sentiment_text()
    texts = [
        build_news_sentiment_text({"title": a.title, "summary": a.body, "why_it_matters": ""})
        for a in all_articles
    ]

    # 일괄 추론
    results: list[SentimentResult] = scorer.score_texts(texts)

    # 날짜별 집계
    aggregates: list[DailyAggregate] = []

    for date in sorted(articles_by_date.keys()):
        articles = articles_by_date[date]
        start, end = date_ranges[date]
        date_results = results[start:end]

        valid_scores = [r.score for r in date_results if r.score is not None]

        coindesk_count = sum(1 for a in articles if a.source == "coindesk")
        alpaca_count = sum(1 for a in articles if a.source == "alpaca")
        count = len(valid_scores)

        if count == 0:
            mean: float | None = None
            std: float | None = None
        elif count == 1:
            mean = valid_scores[0]
            std = None  # ddof=1로 NaN → None
        else:
            avg = sum(valid_scores) / count
            variance = sum((s - avg) ** 2 for s in valid_scores) / (count - 1)
            mean = avg
            std = math.sqrt(variance)

        status = _determine_status(count)

        aggregates.append(
            DailyAggregate(
                date=date,
                mean=mean,
                std=std,
                count=count,
                status=status,
                coindesk_count=coindesk_count,
                alpaca_count=alpaca_count,
            )
        )

    return aggregates
