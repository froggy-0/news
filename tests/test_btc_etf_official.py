from __future__ import annotations

from pathlib import Path

from morning_brief.data.sources import btc_etf_official as official
from morning_brief.models import BitcoinEtfIssuerSnapshot

IBIT_SAMPLE = """
Net Assets of Fund as of Mar 11, 2026 $53,660,350,151
Shares Outstanding as of Mar 11, 2026 1,340,640,000
Daily Volume as of Mar 11, 2026 51,079,056.00
Basket Bitcoin Amount as of Mar 11, 2026 22.47
"""

BITB_SAMPLE = """
Data as of 03/10/2026
Net Assets $4,188,030,760
Shares Outstanding 111,900,000
Daily Volume 9,639,037
Bitcoin in Trust 37,604.17
Bitcoin per Share 0.00033605
"""

BITB_CURRENT_SAMPLE = """
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"fundPageData":{"fundDetailsData":{"netAssets":2725606286.52,"sharesOutstanding":71500000,"volume":3209174}},"proofOfReservesSnapshotData":{"fundName":"BITB","totalReserve":38920.51992677,"timestamp":"2026-03-13T01:01:51.772Z"}}}}
</script>
Data as of 03/11/2026
Net Assets (AUM) $2,725,606,287
Shares Outstanding 71,500,000
Daily Volume (Shares)* 3,209,174
"""

GBTC_SAMPLE = """
Data as of 03/10/2026
ASSETS UNDER MANAGEMENT* $16,100,265,163
SHARES OUTSTANDING 190,850,100
DAILY VOLUME (SHARES)* 3,707,892
TOTAL BITCOIN IN TRUST 193,530.1058
BITCOIN PER SHARE 0.00101403
"""


def test_parse_ibit_snapshot_derives_total_btc_from_basket_amount():
    snapshot = official.parse_ibit_snapshot(IBIT_SAMPLE)

    assert snapshot.ticker == "IBIT"
    assert snapshot.as_of == "Mar 11, 2026"
    assert snapshot.shares_outstanding == 1_340_640_000
    assert snapshot.daily_volume == 51_079_056
    assert snapshot.bitcoin_per_share == round(22.47 / 40_000, 10)
    assert snapshot.total_btc == round(snapshot.shares_outstanding * snapshot.bitcoin_per_share, 8)


def test_parse_bitb_snapshot_reads_direct_holdings_fields():
    snapshot = official.parse_bitb_snapshot(BITB_SAMPLE)

    assert snapshot.ticker == "BITB"
    assert snapshot.as_of == "03/10/2026"
    assert snapshot.total_btc == 37_604.17
    assert snapshot.bitcoin_per_share == 0.00033605


def test_parse_bitb_snapshot_prefers_structured_page_payload_when_available():
    snapshot = official.parse_bitb_snapshot(BITB_CURRENT_SAMPLE)

    assert snapshot.ticker == "BITB"
    assert snapshot.as_of == "03/13/2026"
    assert snapshot.total_btc == 38920.51992677
    assert snapshot.shares_outstanding == 71_500_000
    assert snapshot.daily_volume == 3_209_174
    assert snapshot.bitcoin_per_share == round(38920.51992677 / 71_500_000, 10)


def test_parse_gbtc_snapshot_reads_direct_holdings_fields():
    snapshot = official.parse_gbtc_snapshot(GBTC_SAMPLE)

    assert snapshot.ticker == "GBTC"
    assert snapshot.as_of == "03/10/2026"
    assert snapshot.total_btc == 193_530.1058
    assert snapshot.bitcoin_per_share == 0.00101403


def test_official_btc_etf_cache_roundtrip(tmp_path: Path):
    cache_file = tmp_path / "btc.json"
    snapshots = [
        BitcoinEtfIssuerSnapshot(
            ticker="BITB",
            issuer="Bitwise",
            source_url=official.BITB_URL,
            as_of="03/10/2026",
            shares_outstanding=111_900_000,
            daily_volume=9_639_037,
            aum_usd=4_188_030_760.0,
            total_btc=37_604.17,
            bitcoin_per_share=0.00033605,
        )
    ]

    official.save_official_btc_etf_cache(cache_file, snapshots)
    loaded = official.load_official_btc_etf_cache(cache_file)

    assert loaded["BITB"] == snapshots[0]


def test_fetch_official_btc_etf_snapshots_keeps_partial_success_when_one_issuer_fails(monkeypatch):
    monkeypatch.setattr(
        official,
        "get_text_with_retry",
        lambda url, **kwargs: (_ for _ in ()).throw(official.HttpFetchError("404"))
        if url == official.BITB_URL
        else url,
    )
    monkeypatch.setattr(
        official,
        "parse_ibit_snapshot",
        lambda text: BitcoinEtfIssuerSnapshot(
            ticker="IBIT",
            issuer="iShares",
            source_url=text,
            as_of="03/11/2026",
            shares_outstanding=1,
            daily_volume=1,
            aum_usd=1.0,
            total_btc=1.0,
            bitcoin_per_share=1.0,
        ),
    )
    monkeypatch.setattr(
        official,
        "parse_bitb_snapshot",
        lambda text: (_ for _ in ()).throw(AssertionError("BITB parser should not run")),
    )
    monkeypatch.setattr(
        official,
        "parse_gbtc_snapshot",
        lambda text: BitcoinEtfIssuerSnapshot(
            ticker="GBTC",
            issuer="Grayscale",
            source_url=text,
            as_of="03/11/2026",
            shares_outstanding=1,
            daily_volume=1,
            aum_usd=1.0,
            total_btc=1.0,
            bitcoin_per_share=1.0,
        ),
    )

    snapshots = official.fetch_official_btc_etf_snapshots()

    assert [snapshot.ticker for snapshot in snapshots] == ["GBTC", "IBIT"]
