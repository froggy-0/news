from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from morning_brief.config import load_settings
from morning_brief.data import news
from morning_brief.data.news_rollout import (
    record_news_rollout_run,
    should_reduce_legacy_broad_fallback,
)
from morning_brief.data.news_selection import (
    _dedup_and_rank,
    _has_meaningful_public_interpretation,
    _title_dedup_key,
)
from morning_brief.data.sources.http_client import HttpFetchError
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


def test_preferred_domain_accepts_regulatory_and_official_ir_sources():
    assert news._is_preferred_domain("https://www.federalreserve.gov/newsevents/pressreleases.htm")
    assert news._is_preferred_domain("https://www.sec.gov/news/press-release/example")
    assert news._is_preferred_domain(
        "https://investor.nvidia.com/news/press-release-details/2026/example/default.aspx"
    )


def test_source_tier_promotes_regulatory_domains_to_tier_1():
    packet = news._news_items_to_packet(
        [
            NewsItem(
                title="Fed release",
                url="https://www.federalreserve.gov/newsevents/pressreleases/example.htm",
                source="Federal Reserve",
                published_at=datetime.now(timezone.utc),
            ),
            NewsItem(
                title="NVIDIA IR release",
                url="https://investor.nvidia.com/news/press-release-details/2026/example/default.aspx",
                source="NVIDIA IR",
                published_at=datetime.now(timezone.utc),
            ),
        ]
    )

    assert packet[0]["source_tier"] == "tier_1"
    assert packet[0]["preferred_source"] is True
    assert packet[1]["source_tier"] == "tier_2"
    assert packet[1]["preferred_source"] is True


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


def test_dedup_and_rank_min_output_relaxes_domain_diversity():
    """min_output이 지정되면 도메인 다양성 제한이 결과를 min_output 미만으로 줄이지 않는다."""
    now = datetime.now(timezone.utc)
    # reuters.com 아이템 5개: MAX_ITEMS_PER_DOMAIN=2이므로 일반적으로 2개만 선택됨
    items = [
        NewsItem(
            title=f"Reuters article {i}",
            url=f"https://www.reuters.com/article-{i}/",
            source="Reuters",
            published_at=now - timedelta(minutes=i),
        )
        for i in range(5)
    ]
    result = news._dedup_and_rank(items, max_items=12, min_output=3)
    assert len(result) >= 3


def test_dedup_and_rank_min_output_not_applied_when_ranked_too_few():
    """ranked 자체가 min_output 미만이면 완화 미발동, ranked 전체를 반환한다."""
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title=f"Article {i}",
            url=f"https://www.reuters.com/article-few-{i}/",
            source="Reuters",
            published_at=now - timedelta(minutes=i),
        )
        for i in range(2)
    ]
    result = news._dedup_and_rank(items, max_items=12, min_output=3)
    assert len(result) == 2


def test_dedup_and_rank_min_output_default_preserves_existing_behavior():
    """min_output 기본값(0)이면 기존 동작과 동일하다."""
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title=f"Reuters article {i}",
            url=f"https://www.reuters.com/article-default-{i}/",
            source="Reuters",
            published_at=now - timedelta(minutes=i),
        )
        for i in range(5)
    ]
    result_default = news._dedup_and_rank(items, max_items=12)
    result_explicit_zero = news._dedup_and_rank(items, max_items=12, min_output=0)
    assert len(result_default) == len(result_explicit_zero)


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


def test_fetch_news_uses_broad_rss_only(monkeypatch):
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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

    assert packet[0]["topic"] == "macro"
    assert packet[0]["provider"] == "perplexity_search"
    assert packet[0]["summary"] == "The Fed kept markets steady."
    assert packet[0]["why_it_matters"] == "금리 경로를 읽는 데 도움이 되는 기사예요."
    assert packet[0]["citations"] == ["https://www.reuters.com/world/us/fed-keeps-markets-steady"]


def test_filter_publish_news_drops_weak_candidates_and_below_minimum():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title="Weak source item",
            url="https://example.com/weak-item",
            source="Example",
            published_at=now,
            why_it_matters="Weak source item",
        ),
        NewsItem(
            title="Fed keeps options open",
            url="https://www.reuters.com/world/us/fed-keeps-options-open",
            source="Reuters",
            published_at=now,
            why_it_matters="Fed keeps options open",
        ),
    ]

    kept, audit = news.filter_publish_news(items)

    assert kept == []
    assert audit["below_minimum"] is True
    assert audit["dropped"]["blocked_domain"] == 1


def test_filter_publish_news_keeps_preferred_domains_when_quality_is_sufficient():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title="Fed keeps options open amid sticky inflation",
            url="https://www.reuters.com/world/us/fed-keeps-options-open",
            source="Reuters",
            published_at=now,
            why_it_matters="금리 경로를 읽는 데 도움이 됩니다.",
        ),
        NewsItem(
            title="Nvidia highlights enterprise AI demand",
            url="https://www.cnbc.com/2026/03/22/nvidia-highlights-enterprise-ai-demand.html",
            source="CNBC",
            published_at=now,
            why_it_matters="반도체 수요에 대한 선행 신호입니다.",
        ),
        NewsItem(
            title="Bitcoin ETF inflows stay positive",
            url="https://www.coindesk.com/markets/2026/03/22/bitcoin-etf-inflows-stay-positive/",
            source="CoinDesk",
            published_at=now,
            why_it_matters="기관 수요가 유지되고 있음을 시사합니다.",
        ),
    ]

    kept, audit = news.filter_publish_news(items)

    assert [item.source for item in kept] == ["Reuters", "CNBC", "CoinDesk"]
    assert audit["below_minimum"] is False


def test_filter_public_article_news_candidates_drop_x_items_and_keep_articles():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title="ETF analyst highlights fee pressure",
            url="https://x.com/analyst/status/123",
            source="@ETFAnalyst",
            published_at=now,
            why_it_matters="ETF fee pressure commentary",
        ),
        NewsItem(
            title="Market chatter points to positioning reset",
            url="https://twitter.com/marketdesk/status/456",
            source="Market Desk",
            published_at=now,
            why_it_matters="포지셔닝 조정 가능성을 시사합니다.",
        ),
        NewsItem(
            title="Treasury yields rise as Fed holds optionality",
            url="https://www.reuters.com/world/us/treasury-yields-rise-fed-optionality",
            source="Reuters",
            published_at=now,
            why_it_matters="장기 금리 상승이 성장주 할인율 부담을 키웁니다.",
        ),
    ]

    kept, audit = news.filter_public_article_news_candidates(items)

    assert [item.source for item in kept] == ["Reuters"]
    assert audit["below_minimum"] is False
    assert audit["dropped"]["x_handle_source"] == 1
    assert audit["dropped"]["x_domain_url"] == 1


def test_filter_public_article_news_drops_placeholder_interpretation():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title="Macro update from Reuters",
            url="https://www.reuters.com/world/us/macro-update",
            source="Reuters",
            published_at=now,
            why_it_matters="해당 없음",
        ),
        NewsItem(
            title="Chip demand remains firm",
            url="https://www.cnbc.com/2026/03/22/chip-demand-remains-firm.html",
            source="CNBC",
            published_at=now,
            why_it_matters="반도체 수요가 유지돼 위험 선호를 받칠 수 있습니다.",
        ),
    ]

    kept, audit = news.filter_public_article_news(items)

    assert [item.source for item in kept] == ["CNBC"]
    assert audit["dropped"]["placeholder_public_interpretation"] == 1


def test_filter_public_article_news_allows_reduced_article_count():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            title="Bitcoin ETF flows remain positive",
            url="https://www.coindesk.com/markets/2026/03/22/bitcoin-etf-flows-remain-positive/",
            source="CoinDesk",
            published_at=now,
            why_it_matters="기관 수요가 유지되고 있음을 시사합니다.",
        )
    ]

    kept, audit = news.filter_public_article_news(items)

    assert [item.source for item in kept] == ["CoinDesk"]
    assert audit["below_minimum"] is False


def test_build_news_packet_prefers_perplexity_search_over_sonar_news(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("PERPLEXITY_USE_SONAR_SUMMARY", "true")
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
                why_it_matters="금리 경로를 읽는 데 도움이 되는 기사예요.",
                citations=["https://www.reuters.com/world/us/fed-keeps-markets-steady"],
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news._collect_sonar_summaries",
        lambda *_, **__: (
            {},
            [
                NewsItem(
                    title="monetary20260318a1.htm",
                    url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a1.htm",
                    source="Federal Reserve",
                    published_at=now,
                    topic="macro",
                    provider="perplexity_sonar",
                )
            ],
        ),
    )

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

    assert len(packet) == 1
    assert packet[0]["provider"] == "perplexity_search"
    assert packet[0]["title"] == "Fed keeps markets steady"


def test_build_news_packet_public_context_keeps_articles_and_x_signals_separate(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Treasury yields rise as growth stocks wobble",
                url="https://www.reuters.com/world/us/treasury-yields-rise-growth-stocks-wobble",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                summary="Yields moved higher after the latest Fed messaging.",
                why_it_matters="장기 금리 상승이 성장주 밸류에이션 부담을 키웁니다.",
                citations=[
                    "https://www.reuters.com/world/us/treasury-yields-rise-growth-stocks-wobble"
                ],
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news._collect_sonar_summaries", lambda *_, **__: ({}, [])
    )
    monkeypatch.setattr(
        "morning_brief.data.news._collect_x_keyword_signals",
        lambda *_, **__: (
            [
                news.XSignal(
                    headline="ETF fee war chatter is accelerating",
                    summary="Analysts say a fee war is starting.",
                    why_it_matters="수수료 경쟁 기대가 단기 심리에 우호적일 수 있습니다.",
                    sentiment="bullish",
                    source_handle="EricBalchunas",
                    posted_at=now,
                    topic="bitcoin",
                    citations=["https://x.com/EricBalchunas/status/123"],
                )
            ],
            [
                NewsItem(
                    title="ETF fee war chatter is accelerating",
                    url="https://x.com/EricBalchunas/status/123",
                    source="@EricBalchunas",
                    published_at=now,
                    topic="bitcoin",
                    provider="grok_x_keyword",
                    summary="Analysts say a fee war is starting.",
                    why_it_matters="수수료 경쟁 기대가 단기 심리에 우호적일 수 있습니다.",
                    citations=["https://x.com/EricBalchunas/status/123"],
                )
            ],
            {},
        ),
    )
    monkeypatch.setattr("morning_brief.data.news._collect_grok_web_news", lambda *_, **__: [])

    _, _, _, public_context = news.build_news_packet(settings=load_settings())

    assert [item["source"] for item in public_context["all_news"]] == ["Reuters"]
    assert public_context["source_counts"]["newsAll"] == 1
    assert public_context["source_counts"]["xSignalAll"] == 1
    assert public_context["all_x_signals"][0]["source_handle"] == "EricBalchunas"


def test_build_news_packet_enriches_public_article_news(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Treasury yields rise as growth stocks wobble",
                url="https://www.reuters.com/world/us/treasury-yields-rise-growth-stocks-wobble",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                summary="Yields moved higher after the latest Fed messaging.",
                why_it_matters="Growth stocks face a higher discount-rate burden.",
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news._collect_sonar_summaries", lambda *_, **__: ({}, [])
    )
    monkeypatch.setattr(
        "morning_brief.data.news.enrich_public_news_packet",
        lambda *, items, settings, observer=None: (
            [
                {
                    **item,
                    "summary_ko": "장기 금리가 올라 기술주 부담이 커졌습니다.",
                    "interpretation_ko": "고금리 부담이 성장주 선호를 약하게 만들 수 있습니다.",
                }
                for item in items
            ],
            SimpleNamespace(
                candidate_count=len(items),
                requested_count=len(items),
                success_count=len(items),
                skipped_count=0,
                failed_count=0,
                status="ok",
            ),
        ),
    )

    _, _, _, public_context = news.build_news_packet(settings=load_settings())

    assert (
        public_context["all_news"][0]["summary_ko"] == "장기 금리가 올라 기술주 부담이 커졌습니다."
    )
    assert (
        public_context["all_news"][0]["interpretation_ko"]
        == "고금리 부담이 성장주 선호를 약하게 만들 수 있습니다."
    )


def test_build_news_packet_public_context_includes_public_news_analysis_audit(monkeypatch):
    """public_context에 public_news_analysis 필드가 포함되어야 한다 (Req 1)."""
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Treasury yields rise as growth stocks wobble",
                url="https://www.reuters.com/world/us/treasury-yields-rise-growth-stocks-wobble",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                summary="Yields moved higher.",
                why_it_matters="Growth stocks face pressure.",
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news._collect_sonar_summaries", lambda *_, **__: ({}, [])
    )
    monkeypatch.setattr(
        "morning_brief.data.news.enrich_public_news_packet",
        lambda *, items, settings, observer=None: (
            items,
            SimpleNamespace(
                candidate_count=1,
                requested_count=1,
                success_count=1,
                skipped_count=0,
                failed_count=0,
                status="ok",
            ),
        ),
    )

    _, _, _, public_context = news.build_news_packet(settings=load_settings())

    audit = public_context.get("public_news_analysis")
    assert audit is not None, "public_news_analysis가 public_context에 없음"
    assert audit["candidateCount"] == 1
    assert audit["requestedCount"] == 1
    assert audit["successCount"] == 1
    assert audit["failedCount"] == 0
    assert audit["skippedCount"] == 0
    assert audit["status"] == "ok"
    # 불변식 A: requestedCount == successCount + failedCount
    assert audit["requestedCount"] == audit["successCount"] + audit["failedCount"]
    # 불변식 B: candidateCount == requestedCount + skippedCount
    assert audit["candidateCount"] == audit["requestedCount"] + audit["skippedCount"]


def test_build_news_packet_public_news_analysis_audit_when_disabled(monkeypatch):
    """enrichment 비활성화 시 status=skipped, requestedCount=0, skippedCount=candidateCount."""
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("OPENAI_PUBLIC_NEWS_ANALYSIS_ENABLED", "false")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Treasury yields rise",
                url="https://www.reuters.com/world/us/treasury-yields-rise",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                summary="Yields moved higher.",
                why_it_matters="Growth stocks face pressure.",
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news._collect_sonar_summaries", lambda *_, **__: ({}, [])
    )

    _, _, _, public_context = news.build_news_packet(settings=load_settings())

    audit = public_context.get("public_news_analysis")
    assert audit is not None
    assert audit["status"] == "skipped"
    assert audit["requestedCount"] == 0
    assert audit["skippedCount"] == audit["candidateCount"]


def test_build_news_packet_uses_sonar_news_only_when_search_is_empty(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("PERPLEXITY_USE_SONAR_SUMMARY", "true")
    monkeypatch.setattr("morning_brief.data.news.fetch_news_from_perplexity", lambda **_: [])
    monkeypatch.setattr(
        "morning_brief.data.news._collect_sonar_summaries",
        lambda *_, **__: (
            {},
            [
                NewsItem(
                    title="Fed holds rates",
                    url="https://www.reuters.com/world/us/fed-holds-rates",
                    source="Reuters",
                    published_at=now,
                    topic="macro",
                    provider="perplexity_sonar",
                )
            ],
        ),
    )

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

    assert len(packet) == 1
    assert packet[0]["provider"] == "perplexity_sonar"


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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

    assert len(packet) == 4
    assert {item["topic"] for item in packet} == {"macro", "us_equity", "ai_bigtech", "bitcoin"}


def test_build_news_packet_includes_items_from_any_domain(
    monkeypatch,
):
    """도메인 화이트리스트 제거 후 비선호 도메인 기사도 공개 뉴스에 포함되는지 확인."""
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news_from_perplexity",
        lambda **_: [
            NewsItem(
                title="Macro outlook shifts",
                url="https://alpha.example.ai/macro-outlook",
                source="Alpha Example",
                published_at=now,
                topic="macro",
                provider="perplexity_search",
                why_it_matters="금리 흐름을 읽는 데 도움이 됩니다.",
                citations=["https://alpha.example.ai/macro-outlook"],
            ),
            NewsItem(
                title="US equity breadth narrows",
                url="https://beta.example.ai/equity-breadth",
                source="Beta Example",
                published_at=now - timedelta(hours=1),
                topic="us_equity",
                provider="perplexity_search",
                why_it_matters="미국 증시 흐름을 읽는 데 도움이 됩니다.",
                citations=["https://beta.example.ai/equity-breadth"],
            ),
            NewsItem(
                title="Bitcoin derivatives positioning changes",
                url="https://gamma.example.ai/bitcoin-positioning",
                source="Gamma Example",
                published_at=now - timedelta(hours=2),
                topic="bitcoin",
                provider="perplexity_search",
                why_it_matters="비트코인 수급을 읽는 데 도움이 됩니다.",
                citations=["https://gamma.example.ai/bitcoin-positioning"],
            ),
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_news",
        lambda **_: [
            NewsItem(
                title="Fed tone stays steady",
                url="https://www.reuters.com/world/us/fed-tone-stays-steady",
                source="Reuters",
                published_at=now,
                topic="macro",
                provider="legacy_rss",
                why_it_matters="금리 흐름을 읽는 데 도움이 돼요.",
                citations=["https://www.reuters.com/world/us/fed-tone-stays-steady"],
            )
        ],
    )

    packet, _, _, public_context = news.build_news_packet(settings=load_settings())

    # 도메인 화이트리스트 제거 — 비선호 도메인 기사도 공개 뉴스에 포함되어야 함
    assert public_context["source_counts"]["newsCandidates"] >= 3
    assert public_context["source_counts"]["newsAll"] >= 3
    public_sources = {item["source"] for item in public_context["all_news"]}
    assert "Alpha Example" in public_sources
    assert "Beta Example" in public_sources
    assert "Gamma Example" in public_sources


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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

    assert len(packet) == 4


def test_build_news_packet_omits_grok_signals_when_grok_fails(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RESEARCH_PROVIDER", "perplexity")
    monkeypatch.setenv("ENABLE_OFFICIAL_X_SIGNALS", "true")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
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
            )
        ],
    )
    monkeypatch.setattr(
        "morning_brief.data.news.fetch_official_x_signals",
        lambda **_: (_ for _ in ()).throw(HttpFetchError("grok unavailable")),
    )

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

    assert len(packet) == 1
    assert packet[0]["provider"] == "perplexity_search"
    assert {item["provider"] for item in packet} == {"perplexity_search"}
    assert sum(1 for item in packet if item["official_source"] is True) == 0
    assert {item["topic"] for item in packet} == {"macro"}


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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

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

    packet, _, _, _ = news.build_news_packet(settings=load_settings())

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


# --- _cap_signals_by_topic 테스트 ---


def _make_signal(topic: str, sentiment: str = "neutral") -> object:
    from datetime import datetime, timezone

    from morning_brief.data.sources.grok_x_keyword import XSignal

    return XSignal(
        headline=f"{topic} headline",
        summary=f"{topic} summary",
        why_it_matters=f"{topic} impact",
        sentiment=sentiment,
        source_handle="handle",
        posted_at=datetime.now(timezone.utc),
        topic=topic,
    )


def test_cap_signals_by_topic_limits_per_topic():
    """macro 3개 입력 시 per_topic_max=2이면 2개만 반환한다."""
    signals = [_make_signal("macro") for _ in range(3)]
    result = news._cap_signals_by_topic(signals, total_max=6, per_topic_max=2)
    assert len(result) == 2
    assert all(s.topic == "macro" for s in result)


def test_cap_signals_by_topic_total_max():
    """3 topics × 3개 = 9개지만 total_max=6이면 6개만 반환한다."""
    signals = (
        [_make_signal("macro") for _ in range(3)]
        + [_make_signal("ai_bigtech") for _ in range(3)]
        + [_make_signal("bitcoin") for _ in range(3)]
    )
    result = news._cap_signals_by_topic(signals, total_max=6, per_topic_max=4)
    assert len(result) == 6


def test_cap_signals_by_topic_sentiment_diversity_prefers_different_sentiment():
    """sentiment_diversity=True: bullish 이후 bullish 입력 시 bearish를 우선 선택한다."""
    signals = [
        _make_signal("macro", "bullish"),
        _make_signal("macro", "bullish"),  # 같은 sentiment → deferred
        _make_signal("macro", "bearish"),  # 다른 sentiment → 우선 선택
    ]
    result = news._cap_signals_by_topic(
        signals, total_max=6, per_topic_max=2, sentiment_diversity=True
    )
    assert len(result) == 2
    sentiments = {s.sentiment for s in result}
    assert "bullish" in sentiments
    assert "bearish" in sentiments


def test_cap_signals_by_topic_sentiment_diversity_fallback_same_sentiment():
    """sentiment_diversity=True: 같은 sentiment만 있으면 2개 모두 선택한다."""
    signals = [_make_signal("macro", "bullish") for _ in range(3)]
    result = news._cap_signals_by_topic(
        signals, total_max=6, per_topic_max=2, sentiment_diversity=True
    )
    assert len(result) == 2


def test_cap_signals_by_topic_empty_topic_treated_as_unknown():
    """topic 필드가 빈 문자열인 경우 'unknown'으로 처리해 crash 없이 동작한다."""
    signals = [_make_signal("") for _ in range(3)]
    result = news._cap_signals_by_topic(signals, total_max=6, per_topic_max=2)
    assert len(result) == 2  # unknown으로 묶여 2개 제한


# ─── Title dedup 테스트 ────────────────────────────────────────────────────


def _item(
    title: str,
    url: str,
) -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        source="test",
        published_at=datetime.now(timezone.utc),
        topic="macro",
        provider="perplexity_search",
        summary="summary",
        why_it_matters="impact",
        citations=[],
    )


def test_title_dedup_key_returns_first_40_chars() -> None:
    title = "A" * 50
    assert _title_dedup_key(title) == "a" * 40


def test_title_dedup_key_short_title_disabled() -> None:
    assert _title_dedup_key("short") == ""
    assert _title_dedup_key("123456789") == ""  # 9자


def test_title_dedup_key_normalizes_whitespace() -> None:
    key = _title_dedup_key("Fed  Raises  Rates")
    assert "  " not in key


def test_dedup_and_rank_same_title_different_url_returns_one() -> None:
    title = "Fed raises interest rates by 25 basis points"
    item_a = _item(title, "https://reuters.com/fed-raises")
    item_b = _item(title, "https://bloomberg.com/fed-raises")
    result = _dedup_and_rank([item_a, item_b], max_items=10)
    assert len(result) == 1


def test_dedup_and_rank_different_title_same_url_dedup_by_url() -> None:
    url = "https://reuters.com/article/1"
    item_a = _item("Fed raises rates in surprise move", url)
    item_b = _item("Central bank hikes by a quarter point", url)
    result = _dedup_and_rank([item_a, item_b], max_items=10)
    assert len(result) == 1


def test_dedup_and_rank_short_title_no_title_dedup() -> None:
    """9자 이하 제목은 보조 title dedup 미적용 — URL이 다르면 둘 다 통과한다."""
    item_a = _item("Fed news", "https://reuters.com/fed")
    item_b = _item("Fed news", "https://bloomberg.com/fed")
    result = _dedup_and_rank([item_a, item_b], max_items=10)
    assert len(result) == 2


# ─── Meaningless interpretation 탐지 테스트 ──────────────────────────────


def _news_item_with_why(why: str, summary: str = "") -> NewsItem:
    return NewsItem(
        title="Test",
        url="https://reuters.com/test",
        source="Reuters",
        published_at=None,
        topic="macro",
        provider="perplexity_search",
        summary=summary,
        why_it_matters=why,
        citations=[],
    )


def test_interpretation_na_uppercase_is_meaningless() -> None:
    assert _has_meaningful_public_interpretation(_news_item_with_why("N/A")) is False


def test_interpretation_none_is_meaningless() -> None:
    assert _has_meaningful_public_interpretation(_news_item_with_why("none")) is False


def test_interpretation_no_information_is_meaningless() -> None:
    assert _has_meaningful_public_interpretation(_news_item_with_why("no information")) is False


def test_interpretation_na_with_period_is_meaningless() -> None:
    """'N/A.' → rstrip 후 'n/a' 매칭."""
    assert _has_meaningful_public_interpretation(_news_item_with_why("N/A.")) is False


def test_interpretation_meaningful_text_is_meaningful() -> None:
    assert (
        _has_meaningful_public_interpretation(_news_item_with_why("The Fed raised rates by 25bps"))
        is True
    )


def test_interpretation_korean_없음_is_meaningless() -> None:
    assert _has_meaningful_public_interpretation(_news_item_with_why("없음")) is False


def test_interpretation_korean_해당없음_is_meaningless() -> None:
    assert _has_meaningful_public_interpretation(_news_item_with_why("해당없음")) is False
