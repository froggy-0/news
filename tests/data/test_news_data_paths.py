from __future__ import annotations

from morning_brief.data.storage.news_data_paths import (
    build_publish_paths,
    build_raw_capture_key,
)


def test_publish_paths_deterministic_for_same_date() -> None:
    """Property 1: 동일 날짜 재실행에서도 publish path는 동일해야 한다."""
    a = build_publish_paths(symbol="btc", run_date="2026-04-14")
    b = build_publish_paths(symbol="btc", run_date="2026-04-14")
    assert a == b


def test_publish_paths_format() -> None:
    paths = build_publish_paths(symbol="btc", run_date="2026-04-14")
    assert paths.curated_key == "curated/btc/2026-04-14.json"
    assert paths.analytics_key == "analytics/btc/2026-04-14.json"


def test_raw_capture_key_differs_by_run_id() -> None:
    """Property 1: raw path는 run_id에 따라 달라야 한다."""
    common = dict(
        domain="market",
        provider="fred",
        dataset="rates",
        run_date="2026-04-14",
    )
    key_a = build_raw_capture_key(**common, run_id="run-001")
    key_b = build_raw_capture_key(**common, run_id="run-002")
    assert key_a != key_b


def test_raw_capture_key_format() -> None:
    key = build_raw_capture_key(
        domain="news",
        provider="perplexity_search",
        dataset="macro",
        run_date="2026-04-14",
        run_id="abc123",
    )
    assert key == "raw/news/perplexity_search/macro/2026-04-14/abc123.json"


def test_raw_capture_key_custom_ext() -> None:
    key = build_raw_capture_key(
        domain="market",
        provider="kis",
        dataset="fx",
        run_date="2026-04-14",
        run_id="run-1",
        ext="msgpack",
    )
    assert key.endswith(".msgpack")


def test_publish_paths_different_symbols() -> None:
    btc = build_publish_paths(symbol="btc", run_date="2026-04-14")
    eth = build_publish_paths(symbol="eth", run_date="2026-04-14")
    assert btc.curated_key != eth.curated_key
    assert btc.analytics_key != eth.analytics_key
