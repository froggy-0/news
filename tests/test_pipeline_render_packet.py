from __future__ import annotations

from types import SimpleNamespace


def _market_packet() -> dict:
    return {
        "generated_at_utc": "2026-04-07T00:00:00+00:00",
        "macro": [],
        "korea_watch": [],
        "validated_indices": [
            {
                "canonical_key": "dow30",
                "label": "다우30",
                "ticker": ".DJI",
                "price": 46504.67,
                "resolved_value": 46504.67,
                "change_pct": -0.13,
            }
        ],
        "us_indices": [],
        "tech_stocks": [],
        "data_footer_notes": [],
        "bitcoin": {
            "spot": {
                "canonical_key": "btc",
                "label": "BTC-USD",
                "ticker": "BTC-USD",
                "price": 85000.0,
                "resolved_value": 85000.0,
                "change_pct": 0.3,
            },
            "etf_points": [],
            "fear_greed_value": None,
            "fear_greed_label": None,
            "official_etf_snapshots": [],
            "official_etf_total_btc": None,
            "official_etf_total_aum_usd": None,
        },
    }


def test_run_pipeline_merges_validated_and_korea_indices_into_render_packet(monkeypatch, tmp_path):
    from morning_brief.config import load_settings
    from morning_brief.pipeline import run_pipeline

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()

    published_packets: list[dict] = []
    email_packets: list[dict] = []

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr("morning_brief.pipeline.build_news_packet", lambda **_: ([], {}, [], {}))
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: "SOVEREIGN BRIEF (2026-04-07)\n\n1. 거시 환경\n본문",
    )

    def fake_fetch_newsletter_display_data(*, cache_dir, observer=None):
        assert cache_dir == settings.cache_dir
        assert observer is not None
        return {
            "korea_watch": [],
            "korea_indices": [
                {
                    "canonical_key": "kospi",
                    "label": "코스피",
                    "ticker": "0001",
                    "price": 5450.33,
                    "resolved_value": 5450.33,
                    "change_pct": 1.36,
                },
                {
                    "canonical_key": "kosdaq",
                    "label": "코스닥",
                    "ticker": "1001",
                    "price": 1047.37,
                    "resolved_value": 1047.37,
                    "change_pct": -1.54,
                },
            ],
            "tech_stocks": [],
            "btc_etf_points": [],
        }

    monkeypatch.setattr(
        "morning_brief.pipeline.fetch_newsletter_display_data",
        fake_fetch_newsletter_display_data,
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.publish_public_brief",
        lambda **kwargs: published_packets.append(kwargs["packet"]),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.SesSender",
        lambda _settings: SimpleNamespace(
            send=lambda **kwargs: email_packets.append(kwargs["packet"])
        ),
    )

    briefing = run_pipeline(settings=settings)

    assert briefing.startswith("SOVEREIGN BRIEF")
    assert len(published_packets) == 1
    assert len(email_packets) == 1
    published_packet = published_packets[0]
    email_packet = email_packets[0]
    assert [point["canonical_key"] for point in published_packet["validated_indices"]] == ["dow30"]
    assert [point["canonical_key"] for point in published_packet["korea_indices"]] == [
        "kospi",
        "kosdaq",
    ]
    assert email_packet["korea_indices"] == published_packet["korea_indices"]
