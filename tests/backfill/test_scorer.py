"""FinBERT 스코어러 단위 테스트.

FinBertScorer.score_texts를 mock 처리하여 모델 실제 로딩 없이 실행.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backfill.scorer import (
    DailyAggregate,
    _BackfillFinBertSettings,
    _determine_status,
    score_and_aggregate,
)
from backfill.sources.coindesk import RawArticle


def _make_article(
    id_: str,
    source: str = "coindesk",
    date: str = "2024-01-01",
    score: float | None = 0.5,
) -> tuple[RawArticle, float | None]:
    return RawArticle(
        source=source,  # type: ignore[arg-type]
        article_id=id_,
        date=date,
        title=f"title {id_}",
        body=f"body {id_}",
        published_ts=1704067200,
    ), score


def _run_score_and_aggregate(
    articles_and_scores: list[tuple[RawArticle, float | None]],
) -> list[DailyAggregate]:
    """FinBertScorer.score_texts를 mock하고 score_and_aggregate 실행."""
    articles = [a for a, _ in articles_and_scores]
    scores = [s for _, s in articles_and_scores]

    from morning_brief.data.finbert_sentiment import SentimentResult

    mock_results = [SentimentResult(score=s, confidence=0.9, label="neutral") for s in scores]

    articles_by_date: dict[str, list[RawArticle]] = {}
    for a in articles:
        articles_by_date.setdefault(a.date, []).append(a)

    with patch("backfill.scorer.FinBertScorer") as MockScorer:
        instance = MagicMock()
        instance.score_texts.return_value = mock_results
        MockScorer.return_value = instance

        return score_and_aggregate(articles_by_date)


# ──────────────────────────────────────────────
# sentimentStatus 결정 로직
# ──────────────────────────────────────────────


def test_status_skipped_count_zero() -> None:
    assert _determine_status(0) == "skipped"


def test_status_skipped_count_one() -> None:
    assert _determine_status(1) == "skipped"


def test_status_degraded_count_two() -> None:
    assert _determine_status(2) == "degraded"


def test_status_degraded_count_four() -> None:
    assert _determine_status(4) == "degraded"


def test_status_ok_count_five() -> None:
    assert _determine_status(5) == "ok"


def test_status_ok_count_many() -> None:
    assert _determine_status(20) == "ok"


# ──────────────────────────────────────────────
# count=0: mean=None, std=None, status="skipped"
# ──────────────────────────────────────────────


def test_count_zero_all_none_scores() -> None:
    items = [_make_article("1", score=None)]
    result = _run_score_and_aggregate(items)

    assert result[0].count == 0
    assert result[0].mean is None
    assert result[0].std is None
    assert result[0].status == "skipped"


# ──────────────────────────────────────────────
# count=1: std=None (ddof=1 NaN 처리), status="skipped"
# ──────────────────────────────────────────────


def test_count_one_std_is_none() -> None:
    items = [_make_article("1", score=0.7)]
    result = _run_score_and_aggregate(items)

    assert result[0].count == 1
    assert result[0].mean == pytest.approx(0.7)
    assert result[0].std is None
    assert result[0].status == "skipped"


# ──────────────────────────────────────────────
# count=2: std non-null, status="degraded"
# ──────────────────────────────────────────────


def test_count_two_std_nonnull_degraded() -> None:
    items = [_make_article("1", score=0.2), _make_article("2", score=0.4)]
    result = _run_score_and_aggregate(items)

    assert result[0].count == 2
    assert result[0].std is not None
    assert isinstance(result[0].std, float)
    assert result[0].status == "degraded"


# ──────────────────────────────────────────────
# count=3, 4: degraded
# ──────────────────────────────────────────────


def test_count_three_degraded() -> None:
    items = [_make_article(str(i), score=0.1 * i) for i in range(1, 4)]
    result = _run_score_and_aggregate(items)
    assert result[0].status == "degraded"


def test_count_four_degraded() -> None:
    items = [_make_article(str(i), score=0.1 * i) for i in range(1, 5)]
    result = _run_score_and_aggregate(items)
    assert result[0].status == "degraded"


# ──────────────────────────────────────────────
# count=5: ok
# ──────────────────────────────────────────────


def test_count_five_ok() -> None:
    items = [_make_article(str(i), score=0.1 * i) for i in range(1, 6)]
    result = _run_score_and_aggregate(items)
    assert result[0].status == "ok"


# ──────────────────────────────────────────────
# FinBertScorer 단 한 번 생성
# ──────────────────────────────────────────────


def test_finbert_scorer_created_once() -> None:
    """score_and_aggregate() 호출 시 FinBertScorer.__init__ 1회만 호출."""
    from morning_brief.data.finbert_sentiment import SentimentResult

    articles = [
        RawArticle("coindesk", "1", "2024-01-01", "t1", "b1", 0),
        RawArticle("coindesk", "2", "2024-01-01", "t2", "b2", 0),
        RawArticle("coindesk", "3", "2024-01-02", "t3", "b3", 0),
    ]
    articles_by_date: dict[str, list[RawArticle]] = {
        "2024-01-01": articles[:2],
        "2024-01-02": articles[2:],
    }

    mock_results = [SentimentResult(score=0.3, confidence=0.8, label="neutral")] * 3

    with patch("backfill.scorer.FinBertScorer") as MockScorer:
        instance = MagicMock()
        instance.score_texts.return_value = mock_results
        MockScorer.return_value = instance

        score_and_aggregate(articles_by_date)

        assert MockScorer.call_count == 1  # 단 한 번 생성


# ──────────────────────────────────────────────
# _BackfillFinBertSettings duck typing
# ──────────────────────────────────────────────


def test_backfill_finbert_settings_duck_typing() -> None:
    """_BackfillFinBertSettings로 FinBertScorer 생성 시 AttributeError 없음."""
    from morning_brief.data.finbert_sentiment import FinBertScorer

    settings = _BackfillFinBertSettings()
    # AttributeError가 발생하지 않아야 함 (모델은 lazy load이므로 생성 자체는 OK)
    scorer = FinBertScorer(settings)
    assert scorer is not None


# ──────────────────────────────────────────────
# coindesk_count / alpaca_count
# ──────────────────────────────────────────────


def test_source_counts_tracked_correctly() -> None:
    items = [
        _make_article("1", source="coindesk", score=0.1),
        _make_article("2", source="coindesk", score=0.2),
        _make_article("3", source="alpaca", score=0.3),
    ]
    result = _run_score_and_aggregate(items)

    assert result[0].coindesk_count == 2
    assert result[0].alpaca_count == 1
