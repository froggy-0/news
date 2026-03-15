from __future__ import annotations

import json
from pathlib import Path

from morning_brief.data.market import fetch_bitcoin_snapshot
from morning_brief.data.sources.btc_etf_official import save_official_btc_etf_cache
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.models import BitcoinEtfIssuerSnapshot, MarketPoint
from morning_brief.observability import PipelineObserver


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


def test_fetch_bitcoin_snapshot_calls_stooq_once_per_etf(monkeypatch, tmp_path: Path):
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


def test_fetch_bitcoin_snapshot_keeps_pipeline_alive_when_perplexity_etf_parsing_fails(
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
        lambda **_: (_ for _ in ()).throw(HttpFetchError("broken snapshots")),
    )

    snapshot = fetch_bitcoin_snapshot(cache_dir=tmp_path, perplexity_api_key="pplx-test-key")

    assert snapshot.official_etf_snapshots == []
    assert snapshot.official_etf_total_btc is None
    assert snapshot.official_etf_daily_flow_btc is None


def test_fetch_bitcoin_snapshot_records_empty_official_etf_state(monkeypatch, tmp_path: Path):
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
        lambda **_: [],
    )

    observer = PipelineObserver(output_dir=tmp_path / "observability")
    snapshot = fetch_bitcoin_snapshot(cache_dir=tmp_path, observer=observer)

    assert snapshot.official_etf_snapshots == []
    state_file = tmp_path / "btc_etf" / "state.json"
    assert state_file.exists()
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["reason"] == "empty_snapshots"
    assert any(event["event"] == "btc_etf_reference_empty" for event in observer.events)


def test_fetch_bitcoin_snapshot_uses_stale_official_etf_cache_when_reference_is_empty(
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
        lambda **_: [],
    )

    cache_file = tmp_path / "btc_etf" / "official_snapshots.json"
    save_official_btc_etf_cache(
        cache_file,
        [
            BitcoinEtfIssuerSnapshot(
                ticker="IBIT",
                issuer="iShares",
                source_url="https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf",
                as_of="03/14/2026",
                shares_outstanding=10,
                daily_volume=2,
                aum_usd=100.0,
                total_btc=1.5,
                bitcoin_per_share=0.15,
            )
        ],
    )

    observer = PipelineObserver(output_dir=tmp_path / "observability")
    snapshot = fetch_bitcoin_snapshot(cache_dir=tmp_path, observer=observer)

    assert len(snapshot.official_etf_snapshots) == 1
    assert snapshot.official_etf_snapshots[0].ticker == "IBIT"
    assert snapshot.official_etf_total_btc == 1.5
    assert snapshot.official_etf_daily_flow_btc is None
    state_file = tmp_path / "btc_etf" / "state.json"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["reason"] == "empty_snapshots:stale_cache"
    assert any(event["event"] == "btc_etf_reference_stale_fallback" for event in observer.events)
