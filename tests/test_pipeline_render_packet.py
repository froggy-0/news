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


def test_run_pipeline_scores_public_news_directly(monkeypatch, tmp_path):
    from morning_brief.config import load_settings
    from morning_brief.pipeline import run_pipeline

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()

    published_contexts: list[dict] = []
    email_packets: list[dict] = []

    news_packet = [
        {
            "title": "이메일 뉴스",
            "url": "https://example.com/email-news",
            "summary": "이메일 요약",
            "why_it_matters": "이메일 해설",
        }
    ]
    public_context = {
        "all_news": [
            {
                "title": "공개 뉴스",
                "url": "https://example.com/public-news",
                "summary": "공개 요약",
                "why_it_matters": "공개 해설",
            }
        ],
        "all_x_signals": [],
    }

    def fake_enrich_news(items, settings, observer=None, *, text_builder=None):
        if items is news_packet:
            items[0]["sentiment_score"] = 0.11
            items[0]["sentiment_confidence"] = 0.55
            return "email-ok"
        if items is public_context["all_news"]:
            items[0]["sentiment_score"] = 0.73
            items[0]["sentiment_confidence"] = 0.91
            assert text_builder is not None
            return "public-ok"
        raise AssertionError("unexpected items passed to enrich_news_packet")

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr(
        "morning_brief.pipeline.build_news_packet",
        lambda **_: (news_packet, {}, [], public_context),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: "SOVEREIGN BRIEF (2026-04-07)\n\n1. 거시 환경\n본문",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.fetch_newsletter_display_data",
        lambda **_: {
            "korea_watch": [],
            "korea_indices": [],
            "tech_stocks": [],
            "btc_etf_points": [],
        },
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_news_packet",
        fake_enrich_news,
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_x_signals",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_public_signal_items",
        lambda *args, **kwargs: "skipped",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.publish_public_brief",
        lambda **kwargs: published_contexts.append(kwargs["public_context"]),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.SesSender",
        lambda _settings: SimpleNamespace(
            send=lambda **kwargs: email_packets.append(kwargs["packet"])
        ),
    )

    run_pipeline(settings=settings)

    assert len(published_contexts) == 1
    published_context = published_contexts[0]
    assert published_context["sentiment_status"] == "public-ok"
    assert published_context["all_news"][0]["sentiment_score"] == 0.73
    assert published_context["all_news"][0]["sentiment_confidence"] == 0.91
    assert email_packets[0]["news"][0]["sentiment_score"] == 0.11


def test_run_pipeline_uses_public_news_sentiment_status_over_email_status(monkeypatch, tmp_path):
    from morning_brief.config import load_settings
    from morning_brief.pipeline import run_pipeline

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()

    published_contexts: list[dict] = []

    news_packet = [{"title": "이메일 뉴스", "url": "https://example.com/email-news"}]
    public_context = {
        "all_news": [{"title": "공개 뉴스", "url": "https://example.com/public-news"}],
        "all_x_signals": [],
    }

    def fake_enrich_news(items, settings, observer=None, *, text_builder=None):
        if items is news_packet:
            return "ok"
        if items is public_context["all_news"]:
            return "skipped"
        raise AssertionError("unexpected items passed to enrich_news_packet")

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr(
        "morning_brief.pipeline.build_news_packet",
        lambda **_: (news_packet, {}, [], public_context),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: "SOVEREIGN BRIEF (2026-04-07)\n\n1. 거시 환경\n본문",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.fetch_newsletter_display_data",
        lambda **_: {
            "korea_watch": [],
            "korea_indices": [],
            "tech_stocks": [],
            "btc_etf_points": [],
        },
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_news_packet",
        fake_enrich_news,
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_x_signals",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_public_signal_items",
        lambda *args, **kwargs: "skipped",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.publish_public_brief",
        lambda **kwargs: published_contexts.append(kwargs["public_context"]),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.SesSender",
        lambda _settings: SimpleNamespace(send=lambda **kwargs: None),
    )

    run_pipeline(settings=settings)

    assert published_contexts[0]["sentiment_status"] == "skipped"


def test_run_pipeline_scores_public_x_signal_dicts(monkeypatch, tmp_path):
    from morning_brief.config import load_settings
    from morning_brief.pipeline import run_pipeline

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()

    published_contexts: list[dict] = []
    public_context = {
        "all_news": [],
        "featured_x_signals": [
            {
                "headline": "대표 시그널",
                "summary": "대표 시그널 요약",
                "why_it_matters": "대표 시그널 영향",
            }
        ],
        "all_x_signals": [
            {
                "headline": "대표 시그널",
                "summary": "대표 시그널 요약",
                "why_it_matters": "대표 시그널 영향",
            },
            {
                "headline": "전체 시그널",
                "summary": "전체 시그널 요약",
                "why_it_matters": "전체 시그널 영향",
            },
        ],
    }

    def fake_enrich_news(items, settings, observer=None, *, text_builder=None):
        return "skipped"

    def fake_enrich_public_signals(items, settings, observer=None):
        for index, item in enumerate(items, start=1):
            item["sentiment_score"] = round(0.2 * index, 2)
            item["sentiment_confidence"] = 0.9
        return "ok"

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr(
        "morning_brief.pipeline.build_news_packet",
        lambda **_: ([], {}, [], public_context),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: "SOVEREIGN BRIEF (2026-04-07)\n\n1. 거시 환경\n본문",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.fetch_newsletter_display_data",
        lambda **_: {
            "korea_watch": [],
            "korea_indices": [],
            "tech_stocks": [],
            "btc_etf_points": [],
        },
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_news_packet",
        fake_enrich_news,
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_x_signals",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_public_signal_items",
        fake_enrich_public_signals,
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.publish_public_brief",
        lambda **kwargs: published_contexts.append(kwargs["public_context"]),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.SesSender",
        lambda _settings: SimpleNamespace(send=lambda **kwargs: None),
    )

    run_pipeline(settings=settings)

    published_context = published_contexts[0]
    assert published_context["signal_sentiment_status"] == "ok"
    assert published_context["all_x_signals"][0]["sentiment_score"] == 0.2
    assert published_context["all_x_signals"][1]["sentiment_score"] == 0.4
    assert published_context["featured_x_signals"][0]["sentiment_score"] == 0.2
