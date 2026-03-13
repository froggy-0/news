from __future__ import annotations

from datetime import datetime, timedelta, timezone

from morning_brief.config import load_settings
from morning_brief.data import news
from morning_brief.models import NewsItem



def test_normalize_url_strips_tracking_params():
    raw = "https://example.com/path?a=1&utm_source=x&gclid=123#frag"
    normalized = news._normalize_url(raw)
    assert normalized == "https://example.com/path?a=1"



def test_item_score_prefers_preferred_domain():
    now = datetime.now(timezone.utc)
    preferred = NewsItem(
        title="Fed signals rate path",
        url="https://www.reuters.com/world/us/fed-signals-rate-path/",
        source="Reuters",
        published_at=now,
    )
    non_preferred = NewsItem(
        title="Fed signals rate path",
        url="https://randomblog.example.com/fed-signals-rate-path",
        source="Blog",
        published_at=now,
    )
    assert news._item_score(preferred) > news._item_score(non_preferred)



def test_dedup_and_rank_keeps_highest_scored_duplicate():
    now = datetime.now(timezone.utc)
    low = NewsItem(
        title="Bitcoin ETF flow rises",
        url="https://www.reuters.com/markets/a?utm_source=x",
        source="Reuters",
        published_at=now - timedelta(hours=12),
    )
    high = NewsItem(
        title="Bitcoin ETF flow rises",
        url="https://www.reuters.com/markets/a?utm_campaign=y",
        source="Reuters",
        published_at=now,
    )

    ranked = news._dedup_and_rank([low, high], max_items=5)
    assert len(ranked) == 1
    assert ranked[0].published_at == high.published_at


def test_is_preferred_domain_rejects_substring_spoof():
    assert not news._is_preferred_domain("https://totallynotreuters.com/market")
    assert not news._is_preferred_domain("https://news.reuters.com.evil.tld/path")


def test_domain_score_rejects_substring_spoof():
    assert news._domain_score("https://totallynotreuters.com/market") == 0.0
    assert news._domain_score("https://news.reuters.com.evil.tld/path") == 0.0


def test_dedup_and_rank_limits_single_domain_concentration():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title=f"Reuters market update {i}",
            url=f"https://www.reuters.com/markets/story-{i}",
            source="Reuters",
            published_at=now - timedelta(hours=i),
        )
        for i in range(3)
    ] + [
        NewsItem(
            title="CNBC market update",
            url="https://www.cnbc.com/2026/03/12/market-update.html",
            source="CNBC",
            published_at=now,
        )
    ]

    ranked = news._dedup_and_rank(items, max_items=3)

    reuters_count = sum("reuters.com" in item.url for item in ranked)
    assert len(ranked) == 3
    assert reuters_count == 2


def test_build_news_packet_adds_reliability_metadata(monkeypatch):
    now = datetime.now(timezone.utc)
    sample = [
        NewsItem(
            title="Fed signals patience",
            url="https://www.reuters.com/world/us/fed-signals-patience",
            source="Reuters",
            published_at=now - timedelta(hours=2),
        )
    ]
    monkeypatch.setattr("morning_brief.data.news.fetch_news", lambda **_: sample)
    monkeypatch.setenv("RESEARCH_PROVIDER", "legacy")

    packet = news.build_news_packet(settings=load_settings())

    assert packet[0]["domain"] == "www.reuters.com"
    assert packet[0]["source_tier"] == "tier_1"
    assert packet[0]["preferred_source"] is True
    assert packet[0]["age_hours"] is not None


def test_build_news_packet_uses_legacy_fallback_when_perplexity_is_empty(monkeypatch):
    now = datetime.now(timezone.utc)
    sample = [
        NewsItem(
            title="Bitcoin ETF demand stays firm",
            url="https://www.cnbc.com/2026/03/12/bitcoin-etf-demand.html",
            source="CNBC",
            published_at=now - timedelta(hours=1),
        )
    ]

    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr("morning_brief.data.news.fetch_news_from_perplexity", lambda **_: [])
    monkeypatch.setattr("morning_brief.data.news.fetch_news", lambda **_: sample)

    packet = news.build_news_packet(settings=load_settings())

    assert len(packet) == 1
    assert packet[0]["title"] == "Bitcoin ETF demand stays firm"
    assert packet[0]["domain"] == "www.cnbc.com"


def test_build_news_packet_can_skip_legacy_fallback(monkeypatch):
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr("morning_brief.data.news.fetch_news_from_perplexity", lambda **_: [])
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy fetch should not run")),
    )

    packet = news.build_news_packet(settings=load_settings())

    assert packet == []


def test_build_news_packet_preserves_perplexity_metadata(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Fed keeps markets steady",
                url="https://www.reuters.com/world/us/fed-keeps-markets-steady",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                summary="The Fed kept markets steady.",
                why_it_matters="금리 경로를 읽는 데 도움이 되는 기사예요.",
                citations=["https://www.reuters.com/world/us/fed-keeps-markets-steady"],
            )
        ],
    )

    packet = news.build_news_packet(settings=load_settings())

    assert packet[0]["topic"] == "macro"
    assert packet[0]["provider"] == "perplexity_search"
    assert packet[0]["summary"] == "The Fed kept markets steady."
    assert packet[0]["why_it_matters"] == "금리 경로를 읽는 데 도움이 되는 기사예요."
    assert packet[0]["citations"] == [
        "https://www.reuters.com/world/us/fed-keeps-markets-steady"
    ]


def test_summarize_news_packet_quality_counts_reliability_fields():
    packet = [
        {
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "reuters.com",
            "age_hours": 2.0,
        },
        {
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "example.com",
            "age_hours": 30.0,
        },
    ]

    summary = news.summarize_news_packet_quality(packet)

    assert summary == {
        "count": 2,
        "preferred_count": 1,
        "tier_1_count": 1,
        "unique_domains": 2,
        "fresh_count": 1,
    }
