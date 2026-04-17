from __future__ import annotations

from morning_brief.analysis.sentiment_join.sources.etf_flows import (
    ETF_HISTORY_LOOKBACK_BUFFER_DAYS,
    _history_query_window,
    _rows_to_totals,
)


def test_rows_to_totals_forward_fills_each_ticker_before_aggregation() -> None:
    dates = ["2026-04-16", "2026-04-17"]
    rows = [
        {
            "ticker": "IBIT",
            "as_of_date": "2026-04-16",
            "total_btc": 798_006.67,
            "aum_usd": 59_919_175_838.0,
            "source_type": "official_html",
            "quality_status": "degraded",
        },
        {
            "ticker": "BITB",
            "as_of_date": "2026-04-17",
            "total_btc": 38_077.30003518,
            "aum_usd": 2_858_880_289.73,
            "source_type": "official_json",
            "quality_status": "ok",
        },
    ]

    totals_by_date = _rows_to_totals(rows, dates=dates)

    assert totals_by_date["2026-04-16"]["etf_total_btc"] == 798_006.67
    assert totals_by_date["2026-04-17"]["etf_total_btc"] == 836_083.97003518
    assert totals_by_date["2026-04-17"]["etf_total_aum_usd"] == 62_778_056_127.73


def test_rows_to_totals_skips_critical_and_aggregator_rows() -> None:
    dates = ["2026-04-17"]
    rows = [
        {
            "ticker": "IBIT",
            "as_of_date": "2026-04-17",
            "total_btc": 10.0,
            "aum_usd": 100.0,
            "source_type": "aggregator",
            "quality_status": "degraded",
        },
        {
            "ticker": "BITB",
            "as_of_date": "2026-04-17",
            "total_btc": 20.0,
            "aum_usd": 200.0,
            "source_type": "official_json",
            "quality_status": "critical",
        },
    ]

    totals_by_date = _rows_to_totals(rows, dates=dates)

    assert totals_by_date == {}


def test_rows_to_totals_returns_empty_when_no_valid_rows() -> None:
    totals_by_date = _rows_to_totals([], dates=["2026-04-17"])

    assert totals_by_date == {}


def test_history_query_window_adds_lookback_buffer() -> None:
    query_start, query_end = _history_query_window("2026-04-17", "2026-04-30")

    assert query_start == "2026-03-18"
    assert query_end == "2026-04-30"
    assert ETF_HISTORY_LOOKBACK_BUFFER_DAYS == 30
