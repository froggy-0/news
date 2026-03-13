from __future__ import annotations

from pathlib import Path

import pytest

from morning_brief.data.market import fetch_bitcoin_snapshot
from morning_brief.models import BitcoinEtfIssuerSnapshot, MarketPoint


def _snapshot(
    *,
    ticker: str,
    total_btc: float,
    aum_usd: float,
    shares_outstanding: int,
) -> BitcoinEtfIssuerSnapshot:
    return BitcoinEtfIssuerSnapshot(
        ticker=ticker,
        issuer=ticker,
        source_url=f"https://example.com/{ticker.lower()}",
        as_of="03/10/2026",
        shares_outstanding=shares_outstanding,
        daily_volume=1_000_000,
        aum_usd=aum_usd,
        total_btc=total_btc,
        bitcoin_per_share=round(total_btc / shares_outstanding, 10),
    )


def test_fetch_bitcoin_snapshot_computes_official_daily_flow(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_btc_spot_point",
        lambda: MarketPoint(label="BTC-USD", ticker="BTC-USD", price=80_000.0, change_pct=1.2),
    )
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_fear_greed",
        lambda: (60, "Greed"),
    )
    monkeypatch.setattr(
        "morning_brief.data.market._safe_stooq_point_and_volume",
        lambda label, ticker, stooq_symbol=None: (
            MarketPoint(
                label=label,
                ticker=ticker,
                price=50.0,
                change_pct=1.0,
            ),
            10,
        ),
    )
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_official_btc_etf_snapshots",
        lambda **_: [
            _snapshot(
                ticker="BITB",
                total_btc=37_700.0,
                aum_usd=4_300_000_000.0,
                shares_outstanding=112_000_000,
            ),
            _snapshot(
                ticker="GBTC",
                total_btc=193_400.0,
                aum_usd=16_000_000_000.0,
                shares_outstanding=190_800_000,
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.market.load_official_btc_etf_cache",
        lambda _: {
            "BITB": _snapshot(
                ticker="BITB",
                total_btc=37_600.0,
                aum_usd=4_250_000_000.0,
                shares_outstanding=111_900_000,
            ),
            "GBTC": _snapshot(
                ticker="GBTC",
                total_btc=193_500.0,
                aum_usd=16_100_000_000.0,
                shares_outstanding=190_850_000,
            ),
        },
    )
    monkeypatch.setattr(
        "morning_brief.data.market.save_official_btc_etf_cache", lambda *_, **__: None
    )

    snapshot = fetch_bitcoin_snapshot(cache_dir=tmp_path)

    assert snapshot.official_etf_total_btc == 231_100.0
    assert snapshot.official_etf_total_aum_usd == 20_300_000_000.0
    assert snapshot.official_etf_daily_flow_btc == 0.0
    assert snapshot.official_etf_daily_flow_usd == 0.0
    assert snapshot.official_etf_compared_tickers == ["BITB", "GBTC"]
    assert snapshot.official_etf_supported_tickers == ["BITB", "GBTC"]


def test_fetch_bitcoin_snapshot_leaves_official_flow_empty_without_prior_cache(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_btc_spot_point",
        lambda: MarketPoint(label="BTC-USD", ticker="BTC-USD", price=80_000.0, change_pct=1.2),
    )
    monkeypatch.setattr("morning_brief.data.market._fetch_fear_greed", lambda: (60, "Greed"))
    monkeypatch.setattr(
        "morning_brief.data.market._safe_stooq_point_and_volume",
        lambda label, ticker, stooq_symbol=None: (
            MarketPoint(label=label, ticker=ticker, price=50.0, change_pct=1.0),
            10,
        ),
    )
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_official_btc_etf_snapshots",
        lambda **_: [
            _snapshot(
                ticker="BITB",
                total_btc=37_700.0,
                aum_usd=4_300_000_000.0,
                shares_outstanding=112_000_000,
            )
        ],
    )
    monkeypatch.setattr("morning_brief.data.market.load_official_btc_etf_cache", lambda _: {})
    monkeypatch.setattr(
        "morning_brief.data.market.save_official_btc_etf_cache", lambda *_, **__: None
    )

    snapshot = fetch_bitcoin_snapshot(cache_dir=tmp_path)

    assert snapshot.official_etf_daily_flow_btc is None
    assert snapshot.official_etf_daily_flow_usd is None
    assert snapshot.official_etf_compared_tickers == []


@pytest.mark.skip(reason="Alpha Vantage free tier is intentionally disabled.")
def test_fetch_bitcoin_snapshot_calls_alpha_vantage_once_per_etf_when_key_present():
    pass


def test_fetch_bitcoin_snapshot_calls_stooq_once_per_etf_without_alpha_vantage(
    monkeypatch, tmp_path: Path
):
    calls: list[str] = []
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_btc_spot_point",
        lambda: MarketPoint(label="BTC-USD", ticker="BTC-USD", price=80_000.0, change_pct=1.2),
    )
    monkeypatch.setattr("morning_brief.data.market._fetch_fear_greed", lambda: (60, "Greed"))
    monkeypatch.setattr(
        "morning_brief.data.market._safe_stooq_point_and_volume",
        lambda label, ticker, stooq_symbol=None: (
            calls.append(ticker)
            or MarketPoint(label=label, ticker=ticker, price=50.0, change_pct=1.0),
            10,
        ),
    )
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_official_btc_etf_data",
        lambda **_: ([], None, None, None, None, []),
    )

    snapshot = fetch_bitcoin_snapshot(cache_dir=tmp_path)

    assert [point.ticker for point in snapshot.etf_points] == [
        "IBIT",
        "FBTC",
        "ARKB",
        "BITB",
        "GBTC",
    ]
    assert snapshot.etf_total_volume == 50
    assert calls == ["IBIT", "FBTC", "ARKB", "BITB", "GBTC"]


def test_fetch_bitcoin_snapshot_ignores_alpha_vantage_key_and_uses_stooq(
    monkeypatch, tmp_path: Path
):
    calls: list[str] = []
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_btc_spot_point",
        lambda: MarketPoint(label="BTC-USD", ticker="BTC-USD", price=80_000.0, change_pct=1.2),
    )
    monkeypatch.setattr("morning_brief.data.market._fetch_fear_greed", lambda: (60, "Greed"))
    monkeypatch.setattr(
        "morning_brief.data.market._safe_stooq_point_and_volume",
        lambda label, ticker, stooq_symbol=None: (
            calls.append(ticker)
            or MarketPoint(label=label, ticker=ticker, price=50.0, change_pct=1.0),
            10,
        ),
    )
    monkeypatch.setattr(
        "morning_brief.data.market._fetch_official_btc_etf_data",
        lambda **_: ([], None, None, None, None, []),
    )

    snapshot = fetch_bitcoin_snapshot(alpha_vantage_api_key="demo", cache_dir=tmp_path)

    assert calls == ["IBIT", "FBTC", "ARKB", "BITB", "GBTC"]
    assert len(snapshot.etf_points) == 5
    assert snapshot.etf_total_volume == 50


@pytest.mark.skip(reason="Alpha Vantage free tier is intentionally disabled.")
def test_fetch_bitcoin_snapshot_stops_reusing_alpha_vantage_after_rate_limit():
    pass
