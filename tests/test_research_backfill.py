from __future__ import annotations

from types import SimpleNamespace

from morning_brief import research_backfill as rb
from morning_brief.config import load_settings
from morning_brief.observability import PipelineObserver
from morning_brief.research_backfill import (
    _extract_web_citations,
    _needs_web_search_backfill,
    backfill_news_with_web_search,
)


def test_needs_web_search_backfill_for_low_reliability_news():
    quality = {
        "status": "degraded",
        "news_count": 3,
        "preferred_news_count": 0,
        "tier_1_news_count": 0,
        "unique_news_domains": 1,
        "fresh_news_count": 1,
    }

    assert _needs_web_search_backfill(quality) is True


def test_extract_web_citations_reads_url_annotations():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        annotations=[
                            SimpleNamespace(
                                type="url_citation",
                                title="Reuters",
                                url="https://www.reuters.com/markets/example",
                            )
                        ],
                    )
                ],
            )
        ]
    )

    citations = _extract_web_citations(response)

    assert citations == [{"title": "Reuters", "url": "https://www.reuters.com/markets/example"}]


def test_backfill_news_with_web_search_is_disabled_when_setting_is_off(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "false")
    settings = load_settings()
    packet = {
        "news": [
            {
                "title": "Old item",
                "url": "https://example.com/old",
                "source": "Blog",
                "published_at": "2026-03-13T00:00:00+00:00",
                "domain": "example.com",
                "source_tier": "tier_3",
                "preferred_source": False,
                "age_hours": 10.0,
            }
        ],
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {},
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
        },
    }
    quality = {
        "status": "degraded",
        "news_count": 1,
        "preferred_news_count": 0,
        "tier_1_news_count": 0,
        "unique_news_domains": 1,
        "fresh_news_count": 1,
    }

    merged_news, references = backfill_news_with_web_search(
        packet=packet,
        quality=quality,
        settings=settings,
    )

    assert merged_news == packet["news"]
    assert references == []


class _FakeResponsesAPI:
    def __init__(self, response, calls=None):
        self._response = response
        self._calls = calls if calls is not None else []

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return self._response


class _FakeOpenAIClient:
    def __init__(self, response, calls=None):
        self.responses = _FakeResponsesAPI(response, calls)


def test_backfill_news_with_web_search_records_merged_result(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "true")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path)
    packet = {
        "news": [
            {
                "title": "Old item",
                "url": "https://www.reuters.com/world/us/old-item",
                "source": "Reuters",
                "published_at": "2026-03-13T00:00:00+00:00",
                "domain": "reuters.com",
                "source_tier": "tier_1",
                "preferred_source": True,
                "age_hours": 20.0,
            }
        ],
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {},
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
        },
    }
    quality = {
        "status": "degraded",
        "news_count": 1,
        "preferred_news_count": 1,
        "tier_1_news_count": 1,
        "unique_news_domains": 1,
        "fresh_news_count": 0,
    }
    calls = []
    response = SimpleNamespace(
        output_text=(
            '{"items":[{"title":"Fed officials keep rate path open",'
            '"url":"https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",'
            '"source":"Reuters","published_at":"2026-03-15T00:00:00Z"}]}'
        ),
        output=[],
    )

    monkeypatch.setattr(rb, "OpenAI", lambda api_key: _FakeOpenAIClient(response, calls))
    monkeypatch.setattr(
        rb,
        "render_web_search_prompts",
        lambda **kwargs: ("instructions", "user prompt"),
    )
    monkeypatch.setattr(rb, "build_prompt_cache_key", lambda **kwargs: "cache-key")

    merged_news, references = backfill_news_with_web_search(
        packet=packet,
        quality=quality,
        settings=settings,
        observer=observer,
    )

    assert len(merged_news) >= 1
    assert references == []
    events = [event for event in observer.events if event["event"] == "web_backfill_result"]
    assert len(events) == 1
    assert events[0]["reason"] == "merged"
    assert events[0]["extra_item_count"] == 1
    assert events[0]["items"][0]["domain"] == "reuters.com"
    assert calls[0]["include"] == ["web_search_call.action.sources"]
    assert calls[0]["text"]["format"]["type"] == "json_schema"


def test_backfill_news_with_web_search_records_empty_result(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "true")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path)
    packet = {
        "news": [],
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {},
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
        },
    }
    quality = {
        "status": "degraded",
        "news_count": 0,
        "preferred_news_count": 0,
        "tier_1_news_count": 0,
        "unique_news_domains": 0,
        "fresh_news_count": 0,
    }
    response = SimpleNamespace(output_text='{"items":[]}', output=[])

    monkeypatch.setattr(rb, "OpenAI", lambda api_key: _FakeOpenAIClient(response))
    monkeypatch.setattr(
        rb,
        "render_web_search_prompts",
        lambda **kwargs: ("instructions", "user prompt"),
    )
    monkeypatch.setattr(rb, "build_prompt_cache_key", lambda **kwargs: "cache-key")

    merged_news, references = backfill_news_with_web_search(
        packet=packet,
        quality=quality,
        settings=settings,
        observer=observer,
    )

    assert merged_news == []
    assert references == []
    events = [event for event in observer.events if event["event"] == "web_backfill_result"]
    assert len(events) == 1
    assert events[0]["reason"] == "no_items_parsed"
    assert events[0]["extra_item_count"] == 0
    assert events[0]["output_preview"] == '{"items":[]}'


def test_backfill_news_with_web_search_uses_source_only_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "true")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path)
    packet = {
        "news": [
            {
                "title": "Old item",
                "url": "https://example.com/old",
                "source": "Blog",
                "published_at": "2026-03-13T00:00:00+00:00",
                "domain": "example.com",
                "source_tier": "tier_3",
                "preferred_source": False,
                "age_hours": 20.0,
            }
        ],
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {},
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
        },
    }
    quality = {
        "status": "degraded",
        "news_count": 1,
        "preferred_news_count": 0,
        "tier_1_news_count": 0,
        "unique_news_domains": 1,
        "fresh_news_count": 0,
    }
    response = SimpleNamespace(
        output_text="",
        output=[
            SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(
                    sources=[
                        SimpleNamespace(
                            title="Fed officials keep rate path open",
                            url="https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",
                        )
                    ]
                ),
            )
        ],
    )

    monkeypatch.setattr(rb, "OpenAI", lambda api_key: _FakeOpenAIClient(response))
    monkeypatch.setattr(
        rb,
        "render_web_search_prompts",
        lambda **kwargs: ("instructions", "user prompt"),
    )
    monkeypatch.setattr(rb, "build_prompt_cache_key", lambda **kwargs: "cache-key")

    merged_news, references = backfill_news_with_web_search(
        packet=packet,
        quality=quality,
        settings=settings,
        observer=observer,
    )

    assert len(merged_news) == 2
    assert references == [
        {
            "title": "Fed officials keep rate path open",
            "url": "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",
        }
    ]
    events = [event for event in observer.events if event["event"] == "web_backfill_result"]
    assert len(events) == 1
    assert events[0]["reason"] == "source_only_fallback"
    assert events[0]["extra_item_count"] == 1
    assert events[0]["items"][0]["domain"] == "reuters.com"


def test_extract_web_citations_reads_web_search_call_sources():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(
                    sources=[
                        SimpleNamespace(
                            title="Reuters",
                            url="https://www.reuters.com/markets/example",
                        )
                    ]
                ),
            )
        ]
    )

    citations = _extract_web_citations(response)

    assert citations == [{"title": "Reuters", "url": "https://www.reuters.com/markets/example"}]


def test_fallback_items_from_citations_filters_author_and_pdf_pages():
    items = rb._fallback_items_from_citations(
        [
            {
                "title": "https://bloomberg.com/authors/ARwOaGbWfC8/dana-morgan",
                "url": "https://bloomberg.com/authors/ARwOaGbWfC8/dana-morgan",
            },
            {
                "title": "CDI Index Reconstitution PDF",
                "url": "https://downloads.coindesk.com/cd3/CDI/IA/example.pdf",
            },
            {
                "title": "Fed officials keep rate path open",
                "url": "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",
            },
        ]
    )

    assert len(items) == 1
    assert items[0].url == "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/"


def test_fallback_items_from_citations_derives_title_from_article_url():
    items = rb._fallback_items_from_citations(
        [
            {
                "title": "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",
                "url": "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",
            }
        ]
    )

    assert len(items) == 1
    assert items[0].title == "Fed officials keep rate path open"


def test_fallback_items_from_citations_filters_partner_and_generic_sec_pages():
    items = rb._fallback_items_from_citations(
        [
            {
                "title": "AI to impact: Building the AI-Native Enterprise - Paid Program - WSJ",
                "url": "https://partners.wsj.com/ntt-data/ai-to-impact/building-the-ai-native-enterprise/",
            },
            {
                "title": "Newsroom - SEC.gov",
                "url": "https://www.sec.gov/newsroom",
            },
            {
                "title": "Fed officials keep rate path open",
                "url": "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/",
            },
        ]
    )

    assert len(items) == 1
    assert items[0].url == "https://www.reuters.com/world/us/fed-officials-keep-rate-path-open/"
