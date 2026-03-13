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


def test_dedup_and_rank_keeps_multiple_official_x_sources():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title=f"Official signal {index}",
            url=f"https://x.com/source{index}/status/{index}",
            source=f"@Source{index}",
            published_at=now - timedelta(minutes=index),
            provider="grok_official_x",
        )
        for index in range(3)
    ]

    ranked = news._dedup_and_rank(items, max_items=3)

    assert len(ranked) == 3
    assert {item.source for item in ranked} == {"@Source0", "@Source1", "@Source2"}


def test_collect_from_rss_uses_passed_candidate_limit(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_google_rss",
        lambda **kwargs: captured.update(kwargs) or [],
    )

    news._collect_from_rss(max_items=15, preferred_only=True)

    assert captured["max_items"] == 15


def test_fetch_news_stays_on_rss_path_when_minimum_is_met(monkeypatch):
    rss_item = NewsItem(
        title="Fed signals patience",
        url="https://www.reuters.com/world/us/fed-signals-patience",
        source="Reuters",
        published_at=datetime.now(timezone.utc),
        provider="legacy_rss",
    )
    monkeypatch.setattr("morning_brief.data.news._collect_from_rss", lambda **_: [rss_item] * 3)
    monkeypatch.setattr(
        "morning_brief.data.news._collect_from_newsapi",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("newsapi should not run when rss already meets the minimum")
        ),
    )

    items = news.fetch_news(max_items=3, newsapi_key="", allow_broad_fallback=False)

    assert len(items) == 1
    assert items[0].provider == "legacy_rss"


def test_fetch_news_uses_broad_rss_without_gdelt(monkeypatch):
    now = datetime.now(timezone.utc)
    narrow_item = NewsItem(
        title="Fed signals patience",
        url="https://www.reuters.com/world/us/fed-signals-patience",
        source="Reuters",
        published_at=now,
        provider="legacy_rss",
    )
    broad_item = NewsItem(
        title="Semiconductor shares edge higher",
        url="https://www.cnbc.com/2026/03/14/semiconductor-shares-edge-higher.html",
        source="CNBC",
        published_at=now - timedelta(hours=1),
        provider="legacy_rss",
    )
    calls: list[bool] = []

    def fake_collect_from_rss(*, preferred_only: bool, **_):
        calls.append(preferred_only)
        if preferred_only:
            return [narrow_item]
        return [broad_item]

    monkeypatch.setattr("morning_brief.data.news._collect_from_rss", fake_collect_from_rss)

    items = news.fetch_news(max_items=3, newsapi_key="", allow_broad_fallback=True)

    assert calls == [True, False]
    assert {item.provider for item in items} == {"legacy_rss"}


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
    assert packet[0]["citations"] == ["https://www.reuters.com/world/us/fed-keeps-markets-steady"]


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
                citations=[
                    "https://www.coindesk.com/markets/2026/03/13/bitcoin-etfs-keep-drawing-demand"
                ],
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


def test_build_news_packet_does_not_trigger_legacy_fallback_for_uncited_grok_items(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("ENABLE_OFFICIAL_X_SIGNALS", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("GROK_API_KEY", "grok-test-key")
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
                title="Bitcoin ETFs keep drawing demand",
                url="https://www.coindesk.com/markets/2026/03/13/bitcoin-etfs-keep-drawing-demand",
                source="CoinDesk",
                published_at=now - timedelta(hours=2),
                topic="bitcoin",
                provider="perplexity_search",
                why_it_matters="비트코인 자금 흐름을 읽는 데 도움이 돼요.",
                citations=[
                    "https://www.coindesk.com/markets/2026/03/13/bitcoin-etfs-keep-drawing-demand"
                ],
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_official_x_signals",
        lambda **_: [
            NewsItem(
                title="AMD official update",
                url="https://ir.amd.com/",
                source="@AMD",
                published_at=now - timedelta(minutes=30),
                topic="ai_bigtech",
                provider="grok_official_x",
                why_it_matters="공식 메시지라 직접 확인 근거가 돼요.",
                citations=[],
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy fetch should not run")),
    )

    packet = news.build_news_packet(settings=load_settings())

    assert len(packet) == 4


def test_build_news_packet_merges_official_x_signals_before_legacy(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("ENABLE_OFFICIAL_X_SIGNALS", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("GROK_API_KEY", "grok-test-key")
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
                why_it_matters="금리 경로를 읽는 데 도움이 돼요.",
                citations=["https://www.reuters.com/world/us/fed-tone-stays-steady"],
            ),
            NewsItem(
                title="Nasdaq closes firmer",
                url="https://www.cnbc.com/2026/03/13/nasdaq-closes-firmer.html",
                source="CNBC",
                published_at=now - timedelta(hours=1),
                topic="us_equity",
                provider="perplexity_search",
                why_it_matters="미국 증시 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.cnbc.com/2026/03/13/nasdaq-closes-firmer.html"],
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_official_x_signals",
        lambda **_: [
            NewsItem(
                title="AMD가 데이터센터 투자 계획을 다시 확인했어요",
                url="https://x.com/AMD/status/1",
                source="@AMD",
                published_at=now - timedelta(minutes=30),
                topic="ai_bigtech",
                provider="grok_official_x",
                summary="공식 계정이 투자 계획을 다시 설명했어요.",
                why_it_matters="AI 투자 기대를 해석할 때 직접 참고할 수 있어요.",
                citations=["https://x.com/AMD/status/1"],
            ),
            NewsItem(
                title="Fidelity가 ETF 운용 업데이트를 올렸어요",
                url="https://x.com/Fidelity/status/2",
                source="@Fidelity",
                published_at=now - timedelta(minutes=20),
                topic="bitcoin",
                provider="grok_official_x",
                summary="공식 계정이 ETF 관련 업데이트를 공지했어요.",
                why_it_matters="ETF 수급 해석에 바로 연결할 수 있어요.",
                citations=["https://x.com/Fidelity/status/2"],
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy fetch should not run")),
    )

    packet = news.build_news_packet(settings=load_settings())

    assert len(packet) == 4
    assert {item["provider"] for item in packet} == {"perplexity_search", "grok_official_x"}
    assert sum(1 for item in packet if item["official_source"] is True) == 2
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
        "perplexity_citation_backed_count": 1,
        "perplexity_explained_count": 1,
        "official_signal_count": 0,
    }
