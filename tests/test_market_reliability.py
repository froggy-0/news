from __future__ import annotations

import json
from pathlib import Path

from morning_brief.data.market import build_market_packet
from morning_brief.models import BitcoinSnapshot, MarketPoint


def _point(
    *,
    label: str,
    ticker: str,
    canonical_key: str,
    price: float | None,
    change_pct: float | None,
) -> MarketPoint:
    return MarketPoint(
        label=label,
        ticker=ticker,
        price=price,
        change_pct=change_pct,
        canonical_key=canonical_key,
    )


def _btc_snapshot(point: MarketPoint) -> BitcoinSnapshot:
    return BitcoinSnapshot(
        spot=point,
        etf_points=[],
        etf_total_volume=None,
        fear_greed_value=None,
        fear_greed_label=None,
        official_etf_snapshots=[],
        official_etf_total_btc=None,
        official_etf_total_aum_usd=None,
        official_etf_daily_flow_btc=None,
        official_etf_daily_flow_usd=None,
        official_etf_supported_tickers=[],
        official_etf_compared_tickers=[],
    )


def test_build_market_packet_uses_previous_value_cache_for_missing_points(
    monkeypatch, tmp_path: Path
):
    cache_file = tmp_path / "market" / "last_success_points.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "dxy": {
                    "label": "달러 인덱스",
                    "ticker": "DTWEXBGS",
                    "price": 104.2,
                    "change_pct": 0.3,
                    "canonical_key": "dxy",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "morning_brief.data.market.fetch_macro_points",
        lambda **_: [
            _point(
                label="달러 인덱스",
                ticker="DTWEXBGS",
                canonical_key="dxy",
                price=None,
                change_pct=None,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_tech_stock_points", lambda **_: [])
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_bitcoin_snapshot",
        lambda **_: _btc_snapshot(
            _point(
                label="BTC-USD",
                ticker="BTC-USD",
                canonical_key="btc",
                price=82_000.0,
                change_pct=1.1,
            )
        ),
    )

    packet = build_market_packet(cache_dir=tmp_path)

    dxy = packet["macro"][0]
    assert dxy["price"] == 104.2
    assert dxy["is_previous_value"] is True
    assert dxy["validation_status"] == "previous_value"


def test_build_market_packet_keeps_missing_points_empty_without_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_macro_points",
        lambda **_: [
            _point(
                label="달러 인덱스",
                ticker="DTWEXBGS",
                canonical_key="dxy",
                price=None,
                change_pct=None,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_tech_stock_points", lambda **_: [])
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_bitcoin_snapshot",
        lambda **_: _btc_snapshot(
            _point(
                label="BTC-USD",
                ticker="BTC-USD",
                canonical_key="btc",
                price=82_000.0,
                change_pct=1.1,
            )
        ),
    )

    packet = build_market_packet(cache_dir=tmp_path)

    dxy = packet["macro"][0]
    assert dxy["price"] is None
    assert dxy["resolved_value"] is None
    assert dxy["validation_status"] == "missing"
    assert packet["data_footer_notes"] == [
        "달러 인덱스는 원본 데이터와 마지막 성공 값이 모두 없어 생략했어요."
    ]


def test_build_market_packet_omits_anomalous_values_and_records_footer_note(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_macro_points",
        lambda **_: [
            _point(
                label="달러 인덱스",
                ticker="DTWEXBGS",
                canonical_key="dxy",
                price=119.0,
                change_pct=0.5,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_tech_stock_points", lambda **_: [])
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_bitcoin_snapshot",
        lambda **_: _btc_snapshot(
            _point(
                label="BTC-USD",
                ticker="BTC-USD",
                canonical_key="btc",
                price=82_000.0,
                change_pct=1.1,
            )
        ),
    )

    packet = build_market_packet(cache_dir=tmp_path)

    dxy = packet["macro"][0]
    assert dxy["price"] is None
    assert dxy["raw_value"] == 119.0
    assert dxy["resolved_value"] is None
    assert dxy["validation_status"] == "anomaly"
    assert any("허용 범위" in note for note in packet["data_footer_notes"])
