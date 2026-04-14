"""raw/curated/analytics 저장 레이어 일관성 테스트.

Property 7: 같은 날짜 재실행 시 curated/analytics key는 같고 raw key는 달라야 한다.
"""

from __future__ import annotations

from morning_brief.data.storage.news_data_paths import (
    build_publish_paths,
    build_raw_capture_key,
)


def test_publish_paths_are_idempotent_for_same_date() -> None:
    """동일 날짜 재실행 시 curated/analytics key는 동일해야 한다."""
    first = build_publish_paths(symbol="btc", run_date="2026-04-10")
    second = build_publish_paths(symbol="btc", run_date="2026-04-10")

    assert first.curated_key == second.curated_key
    assert first.analytics_key == second.analytics_key


def test_raw_capture_key_differs_by_run_id() -> None:
    """동일 날짜라도 run_id가 다르면 raw key가 달라야 한다."""
    key_a = build_raw_capture_key(
        domain="market",
        provider="pipeline",
        dataset="market_packet",
        run_date="2026-04-10",
        run_id="abc123",
    )
    key_b = build_raw_capture_key(
        domain="market",
        provider="pipeline",
        dataset="market_packet",
        run_date="2026-04-10",
        run_id="def456",
    )

    assert key_a != key_b
    assert "abc123" in key_a
    assert "def456" in key_b


def test_publish_key_is_overwrite_raw_key_is_append() -> None:
    """publish key에는 run_id가 없고, raw key에는 run_id가 있어야 한다."""
    publish = build_publish_paths(symbol="btc", run_date="2026-04-10")
    raw = build_raw_capture_key(
        domain="news",
        provider="pipeline",
        dataset="news_packet",
        run_date="2026-04-10",
        run_id="xyz789",
    )

    # publish key에는 run_id 없음
    assert "xyz789" not in publish.curated_key
    assert "xyz789" not in publish.analytics_key
    # raw key에는 run_id 있음
    assert "xyz789" in raw


def test_raw_capture_key_structure() -> None:
    """raw key가 raw/{domain}/{provider}/{dataset}/{date}/{run_id}.json 구조를 따르는지 확인."""
    key = build_raw_capture_key(
        domain="market",
        provider="pipeline",
        dataset="market_packet",
        run_date="2026-04-10",
        run_id="r1",
    )
    assert key == "raw/market/pipeline/market_packet/2026-04-10/r1.json"


def test_try_raw_capture_does_not_fail_without_r2_config() -> None:
    """R2 미설정 시 try_raw_capture는 아무 것도 하지 않아야 한다."""
    from unittest.mock import MagicMock

    from morning_brief.raw_capture import try_raw_capture

    settings = MagicMock()
    settings.r2_s3_endpoint = ""
    settings.r2_public_bucket = ""

    # 예외 없이 반환
    try_raw_capture(
        settings=settings,
        run_date="2026-04-10",
        market_packet={"btc": 100},
        news_packet=[],
        public_context={},
    )
