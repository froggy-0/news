"""backfill_news_sentiment UI 헬퍼 테스트."""

from __future__ import annotations

from backfill_news_sentiment import _merge_date_range


def test_merge_date_range_initializes_empty_range() -> None:
    assert _merge_date_range("", "", "2025-07-01", "2025-10-18") == (
        "2025-07-01",
        "2025-10-18",
    )


def test_merge_date_range_expands_existing_range() -> None:
    assert _merge_date_range("2025-08-01", "2025-09-30", "2025-07-15", "2025-10-18") == (
        "2025-07-15",
        "2025-10-18",
    )
