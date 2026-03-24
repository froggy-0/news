from __future__ import annotations

import json
from pathlib import Path

from morning_brief.data.market import (
    _fear_greed_level_label,
    build_market_packet,
    fetch_korea_investor_points,
    fetch_macro_points,
)
from morning_brief.data.market_policy import CANONICAL_KEY_BY_SOURCE
from morning_brief.data.sources.fred import fetch_macro_points_from_fred
from morning_brief.models import BitcoinSnapshot, MarketPoint


def _point(
    *,
    label: str,
    ticker: str,
    canonical_key: str,
    price: float | None,
    change_pct: float | None,
    change_bps: float | None = None,
) -> MarketPoint:
    return MarketPoint(
        label=label,
        ticker=ticker,
        price=price,
        change_pct=change_pct,
        change_bps=change_bps,
        canonical_key=canonical_key,
    )


def _btc_snapshot(point: MarketPoint) -> BitcoinSnapshot:
    return BitcoinSnapshot(
        spot=point,
        etf_points=[],
        fear_greed_value=None,
        fear_greed_label=None,
        official_etf_snapshots=[],
        official_etf_total_btc=None,
        official_etf_total_aum_usd=None,
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
                    "ticker": "DX-Y.NYB",
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
                ticker="DX-Y.NYB",
                canonical_key="dxy",
                price=None,
                change_pct=None,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_tech_stock_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_korea_investor_points", lambda: [])
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
                ticker="DX-Y.NYB",
                canonical_key="dxy",
                price=None,
                change_pct=None,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_tech_stock_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_korea_investor_points", lambda: [])
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
                ticker="DTWEXAFEGS",
                canonical_key="dxy",
                price=135.0,  # (95, 130) 범위 밖 → anomaly
                change_pct=0.5,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_tech_stock_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_korea_investor_points", lambda: [])
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
    assert dxy["raw_value"] == 135.0
    assert dxy["resolved_value"] is None
    assert dxy["validation_status"] == "anomaly"
    assert any("허용 범위" in note for note in packet["data_footer_notes"])


def test_fetch_macro_points_uses_fred_for_dxy_when_available(monkeypatch):
    """dxy가 FRED DTWEXAFEGS에서 수집되면 yfinance fallback을 호출하지 않아야 한다."""
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_macro_points_from_fred",
        lambda _: [
            _point(
                label="미국 10년물 국채금리",
                ticker="DGS10",
                canonical_key="us10y",
                price=4.2,
                change_pct=0.1,
            ),
            _point(
                label="달러 인덱스",
                ticker="DTWEXAFEGS",
                canonical_key="dxy",
                price=107.5,
                change_pct=0.1,
            ),
            _point(
                label="VIX",
                ticker="VIXCLS",
                canonical_key="vix",
                price=18.5,
                change_pct=-1.2,
            ),
        ],
    )

    yfinance_calls: list[str] = []

    def fake_yfinance_point(*, label: str, ticker: str, canonical_key: str, price_scale: float):
        yfinance_calls.append(canonical_key)
        return _point(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
            price=104.3,
            change_pct=0.2,
        )

    monkeypatch.setattr("morning_brief.data.market._safe_yfinance_point", fake_yfinance_point)

    points = fetch_macro_points(fred_api_key="fred-key")

    by_key = {point.canonical_key: point for point in points}
    assert by_key["us10y"].ticker == "DGS10"
    assert by_key["vix"].ticker == "VIXCLS"
    assert by_key["dxy"].ticker == "DTWEXAFEGS"
    assert by_key["dxy"].price == 107.5
    assert "dxy" not in yfinance_calls, "dxy는 FRED에서 수집됐으므로 yfinance fallback 불필요"


def test_fetch_macro_points_from_fred_rounds_rate_change_to_integer_bps(monkeypatch):
    values = {
        "DGS10": (4.26, 4.20),
        "DGS2": (3.76, 3.68),
        "VIXCLS": (25.09, 22.37),
        "DTWEXAFEGS": (107.5, 107.2),
        "BAMLH0A0HYM2": (3.25, 3.20),
    }

    monkeypatch.setattr(
        "morning_brief.data.sources.fred._latest_two_values",
        lambda series_id, api_key: values[series_id],
    )

    points = fetch_macro_points_from_fred("fred-key")
    by_key = {point.canonical_key: point for point in points}

    assert by_key["us10y"].change_bps == 6.0
    assert by_key["us2y"].change_bps == 8.0
    assert by_key["vix"].change_pct == 12.16
    assert by_key["dxy"].ticker == "DTWEXAFEGS"
    assert by_key["hy_spread"].ticker == "BAMLH0A0HYM2"


def test_market_policy_dxy_mapping():
    # DTWEXAFEGS (FRED AFE 달러 지수)는 dxy canonical
    assert CANONICAL_KEY_BY_SOURCE["DTWEXAFEGS"] == "dxy"
    # DX=F (yfinance fallback)도 dxy canonical 유지
    assert CANONICAL_KEY_BY_SOURCE["DX=F"] == "dxy"
    # DX-Y.NYB (하위 호환성) 유지
    assert CANONICAL_KEY_BY_SOURCE["DX-Y.NYB"] == "dxy"
    # DTWEXBGS (FRED broad dollar index)는 제외
    assert "DTWE" + "XBGS" not in CANONICAL_KEY_BY_SOURCE


def test_fetch_korea_investor_points_uses_yfinance_targets(monkeypatch):
    calls: list[tuple[str, str, str, float]] = []

    def fake_yfinance_point(*, label: str, ticker: str, canonical_key: str, price_scale: float):
        calls.append((label, ticker, canonical_key, price_scale))
        return _point(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
            price=1_330.0 if canonical_key == "usdkrw" else 20_150.0,
            change_pct=0.2 if canonical_key == "usdkrw" else -0.4,
        )

    monkeypatch.setattr("morning_brief.data.market._safe_yfinance_point", fake_yfinance_point)

    points = fetch_korea_investor_points()

    assert [point.canonical_key for point in points] == ["usdkrw", "nq_futures"]
    assert calls == [
        ("원/달러 환율", "KRW=X", "usdkrw", 1.0),
        ("나스닥 선물", "NQ=F", "nq_futures", 1.0),
    ]


def test_build_market_packet_korea_watch_is_empty(monkeypatch, tmp_path: Path):
    """build_market_packet()의 korea_watch는 빈 리스트여야 한다.
    usdkrw/nq_futures는 fetch_newsletter_display_data()에서 렌더링 직전에 수집됨."""
    monkeypatch.setattr("morning_brief.data.market.fetch_macro_points", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.market.fetch_us_index_points", lambda **_: [])
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

    assert packet["korea_watch"] == [], "korea_watch는 감성 파이프라인에서 제외됨"
    assert packet["tech_stocks"] == [], "tech_stocks는 감성 파이프라인에서 제외됨"
    assert packet["bitcoin"]["etf_points"] == [], "btc etf_points는 감성 파이프라인에서 제외됨"


def test_fetch_korea_investor_points_available_for_newsletter(monkeypatch):
    """fetch_korea_investor_points()는 여전히 동작하며 뉴스레터 렌더링에서 사용 가능해야 한다."""
    calls: list[tuple[str, str, str, float]] = []

    def fake_yfinance_point(*, label: str, ticker: str, canonical_key: str, price_scale: float):
        calls.append((label, ticker, canonical_key, price_scale))
        return _point(
            label=label,
            ticker=ticker,
            canonical_key=canonical_key,
            price=1_330.0 if canonical_key == "usdkrw" else 20_150.0,
            change_pct=0.2 if canonical_key == "usdkrw" else -0.4,
        )

    monkeypatch.setattr("morning_brief.data.market._safe_yfinance_point", fake_yfinance_point)

    points = fetch_korea_investor_points()

    assert [point.canonical_key for point in points] == ["usdkrw", "nq_futures"]
    assert calls == [
        ("원/달러 환율", "KRW=X", "usdkrw", 1.0),
        ("나스닥 선물", "NQ=F", "nq_futures", 1.0),
    ]


def test_fear_greed_level_label_uses_korean_bands():
    assert _fear_greed_level_label(10) == "극단적 공포"
    assert _fear_greed_level_label(40) == "공포"
    assert _fear_greed_level_label(50) == "중립"
    assert _fear_greed_level_label(60) == "탐욕"
    assert _fear_greed_level_label(90) == "극단적 탐욕"
