from __future__ import annotations

from types import SimpleNamespace

from morning_brief.config import load_settings
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


def test_backfill_news_with_web_search_merges_items(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "true")
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

    monkeypatch.setattr(
        "morning_brief.research_backfill.OpenAI",
        lambda **_: SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **__: SimpleNamespace(
                    output_text='{"items":[{"title":"Fed holds rates","url":"https://www.reuters.com/world/us/fed-holds-rates","source":"Reuters","published_at":"2026-03-13T01:00:00Z","why_it_matters":"Fed path matters"}]}',
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
                                            url="https://www.reuters.com/world/us/fed-holds-rates",
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            )
        ),
    )

    merged_news, references = backfill_news_with_web_search(
        packet=packet,
        quality=quality,
        settings=settings,
    )

    assert any(item["source"] == "Reuters" for item in merged_news)
    assert references[0]["url"] == "https://www.reuters.com/world/us/fed-holds-rates"
