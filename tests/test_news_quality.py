from __future__ import annotations

from datetime import datetime, timedelta, timezone

from morning_brief.config import load_settings
from morning_brief.data import news
from morning_brief.data.news_rollout import (
    record_news_rollout_run,
    should_reduce_legacy_broad_fallback,
)
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


def test_collect_from_rss_uses_passed_candidate_limit(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_google_rss",
        lambda **kwargs: captured.update(kwargs) or [],
    )

    news._collect_from_rss(max_items=15, preferred_only=True)

    assert captured["max_items"] == 15


def test_collect_from_newsapi_uses_passed_candidate_limit(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_newsapi",
        lambda **kwargs: captured.update(kwargs) or [],
    )

    news._collect_from_newsapi(api_key="newsapi-key", max_items=15)

    assert captured["max_items"] == 15


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


def test_build_news_packet_skips_legacy_when_perplexity_quality_is_good(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Fed tone stays steady",
                url="https://www.reuters.com/world/us/fed-tone-stays-steady",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.reuters.com/world/us/fed-tone-stays-steady"],
            ),
            NewsItem(
                title="Nasdaq closes near highs",
                url="https://www.bloomberg.com/news/nasdaq-closes-near-highs",
                source="Bloomberg",
                published_at=now - timedelta(hours=1),
                topic="us_equity",
                provider="perplexity_search",
                why_it_matters="미국 증시 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.bloomberg.com/news/nasdaq-closes-near-highs"],
            ),
            NewsItem(
                title="Nvidia demand remains firm",
                url="https://www.cnbc.com/2026/03/13/nvidia-demand-remains-firm.html",
                source="CNBC",
                published_at=now - timedelta(hours=2),
                topic="ai_bigtech",
                provider="perplexity_search",
                why_it_matters="빅테크 투자 심리를 읽는 데 도움이 돼요.",
                citations=["https://www.cnbc.com/2026/03/13/nvidia-demand-remains-firm.html"],
            ),
            NewsItem(
                title="Bitcoin ETFs keep drawing demand",
                url="https://www.coindesk.com/markets/2026/03/13/bitcoin-etfs-keep-drawing-demand",
                source="CoinDesk",
                published_at=now - timedelta(hours=3),
                topic="bitcoin",
                provider="perplexity_search",
                why_it_matters="비트코인 자금 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.coindesk.com/markets/2026/03/13/bitcoin-etfs-keep-drawing-demand"],
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy fetch should not run")),
    )

    packet = news.build_news_packet(settings=load_settings())

    assert len(packet) == 4
    assert {item["topic"] for item in packet} == {"macro", "us_equity", "ai_bigtech", "bitcoin"}


def test_build_news_packet_uses_legacy_when_perplexity_topics_are_too_narrow(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Fed item 1",
                url="https://www.reuters.com/world/us/fed-item-1",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.reuters.com/world/us/fed-item-1"],
            ),
            NewsItem(
                title="Fed item 2",
                url="https://www.bloomberg.com/news/fed-item-2",
                source="Bloomberg",
                published_at=now - timedelta(hours=1),
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.bloomberg.com/news/fed-item-2"],
            ),
            NewsItem(
                title="Fed item 3",
                url="https://www.cnbc.com/2026/03/13/fed-item-3.html",
                source="CNBC",
                published_at=now - timedelta(hours=2),
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.cnbc.com/2026/03/13/fed-item-3.html"],
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news",
        lambda **_: [
            NewsItem(
                title="Bitcoin ETF demand stays firm",
                url="https://www.coindesk.com/markets/2026/03/13/bitcoin-etf-demand-stays-firm",
                source="CoinDesk",
                published_at=now - timedelta(hours=1),
                topic="bitcoin",
                provider="legacy_rss",
            )
        ],
    )

    packet = news.build_news_packet(settings=load_settings())

    assert len(packet) == 4
    assert {item["provider"] for item in packet} == {"perplexity_search", "legacy_rss"}
    assert {item["topic"] for item in packet} == {"macro", "bitcoin"}


def test_build_news_packet_reduces_broad_legacy_when_recent_runs_are_stable(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")

    for _ in range(3):
        record_news_rollout_run(
            cache_dir=tmp_path,
            fallback_review={
                "count": 4,
                "unique_domains": 4,
                "topic_coverage_count": 4,
                "fresh_count": 4,
                "citation_backed_count": 4,
                "needs_legacy_fallback": False,
                "reasons": [],
            },
            used_legacy=False,
            allow_broad_fallback=True,
            provider_breakdown={"perplexity_search": 4},
        )
    assert should_reduce_legacy_broad_fallback(tmp_path) is True

    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Fed item 1",
                url="https://www.reuters.com/world/us/fed-item-1",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.reuters.com/world/us/fed-item-1"],
            ),
            NewsItem(
                title="Fed item 2",
                url="https://www.bloomberg.com/news/fed-item-2",
                source="Bloomberg",
                published_at=now - timedelta(hours=1),
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.bloomberg.com/news/fed-item-2"],
            ),
            NewsItem(
                title="Fed item 3",
                url="https://www.cnbc.com/2026/03/13/fed-item-3.html",
                source="CNBC",
                published_at=now - timedelta(hours=2),
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.cnbc.com/2026/03/13/fed-item-3.html"],
            ),
        ],
    )

    captured: dict[str, object] = {}

    def _fake_fetch_news(**kwargs):
        captured.update(kwargs)
        return [
            NewsItem(
                title="Bitcoin ETF demand stays firm",
                url="https://www.coindesk.com/markets/2026/03/13/bitcoin-etf-demand-stays-firm",
                source="CoinDesk",
                published_at=now - timedelta(hours=1),
                topic="bitcoin",
                provider="legacy_rss",
            )
        ]

    monkeypatch.setattr("morning_brief.data.news.fetch_news", _fake_fetch_news)

    packet = news.build_news_packet(settings=load_settings())

    assert captured["allow_broad_fallback"] is False
    assert len(packet) == 4


def test_summarize_news_packet_quality_counts_reliability_fields():
    packet = [
        {
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "reuters.com",
            "age_hours": 2.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.reuters.com/world/us/fed"],
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
        "topic_coverage_count": 1,
        "citation_backed_count": 1,
        "explained_count": 1,
        "perplexity_item_count": 1,
    }
