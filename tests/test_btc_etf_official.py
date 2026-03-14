from __future__ import annotations

import json
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


def test_reference_prompt_renders_today_without_breaking_json_example():
    rendered = official._render_reference_prompt(official.date(2026, 3, 14))

    assert "2026-03-14" in rendered
    assert '"snapshots": [' in rendered
    assert "{today}" not in rendered


def test_parse_reference_snapshot_response_keeps_only_valid_official_entries():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "snapshots": [
                                {
                                    "ticker": "IBIT",
                                    "issuer": "iShares",
                                    "source_url": official.IBIT_URL,
                                    "as_of": "03/11/2026",
                                    "shares_outstanding": "1,340,640,000",
                                    "daily_volume": "51,079,056",
                                    "aum_usd": "$53,660,350,151",
                                    "total_btc": "752,989.52",
                                    "bitcoin_per_share": "0.00056165",
                                },
                                {
                                    "ticker": "BITB",
                                    "issuer": "Bitwise",
                                    "source_url": "https://example.com/not-official",
                                    "as_of": "03/11/2026",
                                    "shares_outstanding": 71_500_000,
                                    "daily_volume": 3_209_174,
                                    "aum_usd": 2_725_606_287,
                                    "total_btc": 38_920.51992677,
                                    "bitcoin_per_share": 0.00054434,
                                },
                            ]
                        }
                    )
                }
            }
        ]
    }

    snapshots = official._parse_reference_snapshot_response(payload)

    assert [snapshot.ticker for snapshot in snapshots] == ["IBIT"]
    assert snapshots[0].aum_usd == 53_660_350_151.0
    assert snapshots[0].total_btc == 752_989.52


def test_parse_reference_snapshot_response_accepts_member_only_json():
    payload = {
        "choices": [
            {
                "message": {
                    "content": """
                    "snapshots": [
                      {
                        "ticker": "IBIT",
                        "issuer": "iShares",
                        "source_url": "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf",
                        "as_of": "03/11/2026",
                        "shares_outstanding": 1340640000,
                        "daily_volume": 51079056,
                        "aum_usd": 53660350151,
                        "total_btc": 752989.52,
                        "bitcoin_per_share": 0.00056165
                      }
                    ]
                    """.strip()
                }
            }
        ]
    }

    snapshots = official._parse_reference_snapshot_response(payload)

    assert [snapshot.ticker for snapshot in snapshots] == ["IBIT"]
    assert snapshots[0].source_url == official.IBIT_URL


def test_parse_reference_snapshot_response_accepts_string_wrapped_member_json():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        """
                        "snapshots": [
                          {
                            "ticker": "IBIT",
                            "issuer": "iShares",
                            "source_url": "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf",
                            "as_of": "03/11/2026",
                            "shares_outstanding": 1340640000,
                            "daily_volume": 51079056,
                            "aum_usd": 53660350151,
                            "total_btc": 752989.52,
                            "bitcoin_per_share": 0.00056165
                          }
                        ]
                        """.strip()
                    )
                }
            }
        ]
    }

    snapshots = official._parse_reference_snapshot_response(payload)

    assert [snapshot.ticker for snapshot in snapshots] == ["IBIT"]
    assert snapshots[0].source_url == official.IBIT_URL


def test_parse_reference_snapshot_response_accepts_nested_snapshot_payload():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "result": {
                                "snapshots": [
                                    {
                                        "ticker": "IBIT",
                                        "issuer": "iShares",
                                        "source_url": official.IBIT_URL,
                                        "as_of": "03/11/2026",
                                        "shares_outstanding": 1340640000,
                                        "daily_volume": 51079056,
                                        "aum_usd": 53660350151,
                                        "total_btc": 752989.52,
                                        "bitcoin_per_share": 0.00056165,
                                    }
                                ]
                            }
                        }
                    )
                }
            }
        ]
    }

    snapshots = official._parse_reference_snapshot_response(payload)

    assert [snapshot.ticker for snapshot in snapshots] == ["IBIT"]
    assert snapshots[0].source_url == official.IBIT_URL


def test_parse_reference_snapshot_response_includes_preview_on_failure():
    payload = {
        "choices": [
            {
                "message": {
                    "content": ' \n  "snapshots": [oops not json at all',
                }
            }
        ]
    }

    try:
        official._parse_reference_snapshot_response(payload)
    except Exception as exc:
        assert "preview=" in str(exc)
        assert '"snapshots": [oops not json at all' in str(exc)
    else:
        raise AssertionError("HttpFetchError was expected")


def test_fetch_official_btc_etf_snapshots_uses_perplexity_request(monkeypatch):
    expected = [
        BitcoinEtfIssuerSnapshot(
            ticker="IBIT",
            issuer="iShares",
            source_url=official.IBIT_URL,
            as_of="03/11/2026",
            shares_outstanding=1,
            daily_volume=1,
            aum_usd=1.0,
            total_btc=1.0,
            bitcoin_per_share=1.0,
        )
    ]
    captured: dict[str, str] = {}

    def fake_request(api_key: str, *, observer=None):
        captured["api_key"] = api_key
        assert observer is None
        return expected

    monkeypatch.setattr(official, "_request_reference_snapshots", fake_request)

    snapshots = official.fetch_official_btc_etf_snapshots(api_key="pplx-test-key")

    assert snapshots == expected
    assert captured["api_key"] == "pplx-test-key"
