from __future__ import annotations

import pytest

from morning_brief.analysis.sentiment_join.sources.etf_flows import (
    ETF_HISTORY_LOOKBACK_BUFFER_DAYS,
    _history_query_window,
    _rows_to_totals,
    fetch_etf_flow_features,
)


def test_rows_to_totals_forward_fills_each_ticker_before_aggregation() -> None:
    # BITB는 ETF_ANALYSIS_TICKERS에서 제거됐으므로 IBIT 두 날짜로 ffill 테스트
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
            "ticker": "IBIT",
            "as_of_date": "2026-04-17",
            "total_btc": 800_000.0,
            "aum_usd": 60_000_000_000.0,
            "source_type": "official_html",
            "quality_status": "ok",
        },
    ]

    totals_by_date = _rows_to_totals(rows, dates=dates)

    assert totals_by_date["2026-04-16"]["etf_total_btc"] == 798_006.67
    assert totals_by_date["2026-04-17"]["etf_total_btc"] == 800_000.0
    assert totals_by_date["2026-04-17"]["etf_total_aum_usd"] == 60_000_000_000.0


def test_rows_to_totals_skips_bitb_rows() -> None:
    # BITB는 ETF_ANALYSIS_TICKERS에 없으므로 입력에 있어도 무시됨
    dates = ["2026-04-17"]
    rows = [
        {
            "ticker": "BITB",
            "as_of_date": "2026-04-17",
            "total_btc": 38_077.3,
            "aum_usd": 2_858_880_289.73,
            "source_type": "official_json",
            "quality_status": "ok",
        },
    ]

    totals_by_date = _rows_to_totals(rows, dates=dates)

    assert totals_by_date == {}


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


def test_fetch_etf_flow_features_marks_latest_snapshot_fallback_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "morning_brief.analysis.sentiment_join.sources.etf_flows._query_gold_history",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "morning_brief.analysis.sentiment_join.sources.etf_flows._fallback_latest_snapshot",
        lambda *args, **kwargs: [
            {
                "ticker": "IBIT",
                "as_of_date": "2026-04-18",
                "total_btc": 10.0,
                "aum_usd": 100.0,
                "source_type": "official_html",
                "quality_status": "ok",
            }
        ],
    )

    df = fetch_etf_flow_features("2026-04-16", "2026-04-18")

    assert df.attrs["source_mode"] == "latest_snapshot_fallback"
    assert df.attrs["history_non_null_days"] == 1
    assert df.attrs["requested_days"] == 3
    assert df.attrs["history_coverage_ratio"] == 0.3333
    assert df.attrs["history_quality_status"] == "degraded"


def test_etf_analysis_tickers_does_not_include_bitb() -> None:
    """BITB는 히스토리 백필 소스 없으므로 분석 티커에서 의도적으로 제외됨 (회귀 방지)."""
    from morning_brief.analysis.sentiment_join.sources.etf_flows import ETF_ANALYSIS_TICKERS

    assert "BITB" not in ETF_ANALYSIS_TICKERS


def test_fetch_etf_flow_features_marks_gold_history_as_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "morning_brief.analysis.sentiment_join.sources.etf_flows._query_gold_history",
        lambda *args, **kwargs: [
            {
                "ticker": "IBIT",
                "as_of_date": "2026-04-16",
                "total_btc": 10.0,
                "aum_usd": 100.0,
                "source_type": "official_html",
                "quality_status": "ok",
            },
            {
                "ticker": "IBIT",
                "as_of_date": "2026-04-17",
                "total_btc": 11.0,
                "aum_usd": 110.0,
                "source_type": "official_html",
                "quality_status": "ok",
            },
        ],
    )
    monkeypatch.setattr(
        "morning_brief.analysis.sentiment_join.sources.etf_flows._fallback_latest_snapshot",
        lambda *args, **kwargs: [],
    )

    df = fetch_etf_flow_features("2026-04-16", "2026-04-18")

    assert df.attrs["source_mode"] == "gold_history"
    assert df.attrs["history_non_null_days"] == 3
    assert df.attrs["history_coverage_ratio"] == 1.0
    assert df.attrs["history_quality_status"] == "ok"
