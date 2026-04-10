from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.sources import perplexity_search as ps
from morning_brief.data.sources import provider_runtime
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.observability import PipelineObserver


class _SearchResource:
    def __init__(self, responses, calls):
        self._responses = list(responses)
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _Client:
    def __init__(self, responses, calls):
        self.search = _SearchResource(responses, calls)


class _SDKResponse:
    def __init__(self, payload, *, usage=None, model_extra=None):
        self._payload = payload
        self.usage = usage
        self.model_extra = model_extra or {}

    def model_dump(self):
        return self._payload


class _StatusError(ps.APIStatusError):
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.response = type("_Response", (), {"text": text})()


class _TimeoutError(ps.APITimeoutError):
    def __init__(self):
        Exception.__init__(self, "timeout")
        self.request = None


def test_fetch_news_from_perplexity_calls_search_api_with_expected_payload(monkeypatch):
    calls = []

    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="macro retry",
            ),
        ),
    )
    monkeypatch.setattr(ps, "TOPIC_RESULT_TARGET", 1)
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Fed keeps options open",
                                "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                                "snippet": "The Fed kept its options open.",
                                "date": "2026-03-13T01:00:00Z",
                            }
                        ]
                    }
                )
            ],
            calls,
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(calls) == 1
    assert calls[0]["query"] == "macro query"
    assert calls[0]["search_language_filter"] == ["en"]
    assert calls[0]["max_results"] == ps.SEARCH_MAX_RESULTS
    # deny list가 적용되는지 확인
    domain_filter = calls[0]["search_domain_filter"]
    assert all(v.startswith("-") for v in domain_filter)
    assert "search_mode" not in calls[0]
    assert items[0].source == "Reuters"
    assert items[0].provider == "perplexity_search"
    assert items[0].topic == "macro"
    assert items[0].summary == "The Fed kept its options open."
    assert items[0].citations == ["https://www.reuters.com/world/us/fed-keeps-options-open"]


def test_fetch_news_from_perplexity_retries_with_topic_retry_query(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "_utc_now", lambda: datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc))

    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="bitcoin",
                query="bitcoin query",
                retry_query="bitcoin retry",
                retry_recency_filter="week",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "ETF flow stays positive",
                                "url": "https://www.coindesk.com/markets/2026/03/13/etf-flow-stays-positive/",
                                "snippet": "ETF flow stayed positive overnight.",
                                "date": "2026-03-13",
                            }
                        ]
                    }
                ),
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Bitcoin regulation stays in focus",
                                "url": "https://www.coindesk.com/policy/2026/03/13/bitcoin-regulation-stays-in-focus/",
                                "snippet": "Regulation remained a focus.",
                                "date": "2026-03-13T02:00:00Z",
                            }
                        ]
                    }
                ),
            ],
            calls,
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert [call["query"] for call in calls] == ["bitcoin query", "bitcoin retry"]
    # 2026-03-15는 일요일이므로 주말 recency가 "week"으로 적용됨
    assert calls[0]["search_recency_filter"] == "week"
    assert calls[0]["search_language_filter"] == ["en"]
    assert calls[1]["search_recency_filter"] == "week"
    assert calls[1]["search_language_filter"] == ["en"]
    assert len(items) == 2
    assert items[0].topic == "bitcoin"
    assert items[1].why_it_matters
    assert items[0].published_at.isoformat() == "2026-03-13T12:00:00+00:00"


def test_fetch_news_from_perplexity_uses_recency_retry_when_first_search_empty(
    monkeypatch, tmp_path
):
    calls = []
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(ps, "_utc_now", lambda: datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="bitcoin",
                query="bitcoin query",
                retry_query="bitcoin retry",
                retry_recency_filter="week",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse({"results": []}),
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "SEC clarifies timeline for spot bitcoin ETF filing",
                                "url": "https://www.sec.gov/newsroom/press-releases/2026-42",
                                "snippet": "SEC update",
                                "date": "2026-03-14T03:00:00Z",
                            }
                        ]
                    }
                ),
            ],
            calls,
        ),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert [call["query"] for call in calls] == ["bitcoin query", "bitcoin retry"]
    # 2026-03-15는 일요일이므로 주말 recency가 "week"으로 적용됨
    assert calls[0]["search_recency_filter"] == "week"
    assert calls[0]["search_language_filter"] == ["en"]
    assert calls[1]["search_recency_filter"] == "week"
    assert calls[1]["search_language_filter"] == ["en"]
    assert len(items) == 1
    assert items[0].url == "https://www.sec.gov/newsroom/press-releases/2026-42"
    widen_events = [
        event for event in observer.events if event["event"] == "perplexity_search_widened"
    ]
    assert [event["stage"] for event in widen_events] == ["recency_retry"]


def test_search_once_normalizes_domain_filters_for_api_request():
    calls = []
    client = _Client(
        [
            _SDKResponse(
                {
                    "results": [
                        {
                            "title": "Fed keeps options open",
                            "url": "https://www.ft.com/content/abcd1234",
                            "snippet": "FT article.",
                            "date": "2026-03-13T01:00:00Z",
                        }
                    ]
                }
            )
        ],
        calls,
    )

    ps._search_once(
        client=client,
        query="macro query",
        recency_filter="day",
    )

    # deny list가 적용되는지 확인
    domain_filter = calls[0]["search_domain_filter"]
    assert all(v.startswith("-") for v in domain_filter)
    assert any("markets.ft.com" in v for v in domain_filter)


def test_fetch_news_from_perplexity_supports_multi_query_results(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query=("macro one", "macro two"),
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(ps, "TOPIC_RESULT_TARGET", 1)
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            [
                                {
                                    "title": "Fed keeps options open",
                                    "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                                    "snippet": "Reuters macro story.",
                                    "date": "2026-03-13T01:00:00Z",
                                }
                            ],
                            [
                                {
                                    "title": "Treasury yields slip after inflation update",
                                    "url": "https://www.reuters.com/world/us/treasury-yields-slip-after-inflation-update",
                                    "snippet": "Reuters rates story.",
                                    "date": "2026-03-13T02:00:00Z",
                                }
                            ],
                        ]
                    }
                )
            ],
            calls,
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert calls[0]["query"] == ["macro one", "macro two"]
    assert len(items) == 2
    assert items[0].source == "Reuters"


def test_fetch_news_from_perplexity_uses_recency_retry_before_giving_up(monkeypatch, tmp_path):
    calls = []
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(ps, "_utc_now", lambda: datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(ps, "TOPIC_RESULT_TARGET", 1)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="macro retry",
                retry_recency_filter="week",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse({"results": []}),
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Treasury yields edge lower after Fed remarks",
                                "url": "https://www.reuters.com/world/us/treasury-yields-edge-lower-after-fed-remarks/",
                                "snippet": "Reuters story",
                                "last_updated": "2026-03-14T03:00:00Z",
                            }
                        ]
                    }
                ),
            ],
            calls,
        ),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert len(calls) == 2
    # 2026-03-15는 일요일이므로 주말 recency가 "week"으로 적용됨
    assert calls[0]["search_recency_filter"] == "week"
    assert calls[1]["search_recency_filter"] == "week"
    assert len(items) == 1
    widen_events = [
        event for event in observer.events if event["event"] == "perplexity_search_widened"
    ]
    assert [event["stage"] for event in widen_events] == ["recency_retry"]


def test_fetch_news_from_perplexity_filters_sponsored_in_retry(monkeypatch, tmp_path):
    calls = []
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(ps, "_utc_now", lambda: datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(ps, "TOPIC_RESULT_TARGET", 1)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="macro retry",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse({"results": []}),
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Investing in Gold: Is Gold Still Considered a Safe Bet",
                                "url": "https://sponsored.bloomberg.com/article/investing-in-gold",
                                "snippet": "Sponsored content",
                                "date": "2023-01-19",
                            }
                        ]
                    }
                ),
            ],
            calls,
        ),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert items == []


def test_parse_results_filters_sponsored_bloomberg_pages():
    topic = ps.SearchTopic(
        name="macro",
        query="macro query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Investing in Gold: Is Gold Still Considered a Safe Bet",
                    "url": "https://sponsored.bloomberg.com/article/investing-in-gold",
                    "snippet": "Sponsored content",
                    "date": "2026-03-13",
                },
                {
                    "title": "Treasury yields edge lower after inflation report",
                    "url": "https://www.bloomberg.com/news/articles/2026-03-13/treasury-yields-edge-lower-after-inflation-report",
                    "snippet": "Bloomberg article",
                    "date": "2026-03-13",
                },
            ]
        },
        topic=topic,
    )

    assert len(items) == 1
    assert items[0].source == "Bloomberg"


def test_fetch_news_from_perplexity_filters_low_quality_domain(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="us_equity",
                query="equity query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Reddit discussion about market trends today",
                                "url": "https://www.reddit.com/r/stocks/market-story",
                                "snippet": "ignore",
                                "date": "2026-03-13T01:00:00Z",
                            }
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert items == []


def test_fetch_news_from_perplexity_filters_non_newsroom_apple_urls(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="us_equity",
                query="ai query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Polish-English Language App App - App Store",
                                "url": "https://apps.apple.com/me/app/polish-english-language-app/id6470241051",
                                "snippet": "ignore",
                                "date": "2026-03-13T01:00:00Z",
                            },
                            {
                                "title": "Apple unveils new tools for developers",
                                "url": "https://www.apple.com/newsroom/2026/03/apple-unveils-new-tools-for-developers/",
                                "snippet": "Apple shared a newsroom update.",
                                "date": "2026-03-13T02:00:00Z",
                            },
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(items) == 1
    assert items[0].url.startswith("https://www.apple.com/newsroom/")


def test_fetch_news_from_perplexity_filters_service_status_pages(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="us_equity",
                query="ai query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Broadcom Service Status",
                                "url": "https://status.broadcom.com",
                                "snippet": "ignore",
                                "date": "2026-03-14T00:00:00Z",
                            },
                            {
                                "title": "Broadcom outlines new networking roadmap",
                                "url": "https://www.broadcom.com/company/news/product-releases/example",
                                "snippet": "Broadcom shared an update.",
                                "date": "2026-03-14T01:00:00Z",
                            },
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(items) == 1
    assert items[0].url == "https://www.broadcom.com/company/news/product-releases/example"


def test_fetch_news_from_perplexity_filters_paid_partner_pages(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="us_equity",
                query="ai query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "AI to impact: Building the AI-Native Enterprise - Paid Program - WSJ",
                                "url": "https://partners.wsj.com/ntt-data/ai-to-impact/building-the-ai-native-enterprise/",
                                "snippet": "ignore",
                                "date": "2026-03-14T00:00:00Z",
                            },
                            {
                                "title": "Nvidia suppliers track another AI spending boost",
                                "url": "https://www.reuters.com/world/us/nvidia-suppliers-track-another-ai-spending-boost/",
                                "snippet": "Reuters story",
                                "date": "2026-03-14T01:00:00Z",
                            },
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(items) == 1
    assert items[0].source == "Reuters"


def test_fetch_news_from_perplexity_filters_statuspage_urls(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Federal Reserve Status Page",
                                "url": "https://statuspage.example.com/fed",
                                "snippet": "ignore",
                                "date": "2026-03-14",
                            },
                            {
                                "title": "Fed governor says inflation path remains uneven",
                                "url": "https://www.federalreserve.gov/newsevents/speech/example.htm",
                                "snippet": "Federal Reserve speech",
                                "date": "2026-03-14",
                            },
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(items) == 1
    assert items[0].url == "https://www.federalreserve.gov/newsevents/speech/example.htm"


def test_fetch_news_from_perplexity_filters_sec_listing_pages_and_coindesk_data(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="bitcoin",
                query="bitcoin query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "CoinDesk Data: Institutional Grade Digital Asset Data Solutions",
                                "url": "https://data.coindesk.com",
                                "snippet": "ignore",
                                "date": "2026-03-13",
                            },
                            {
                                "title": "What's New - SEC.gov",
                                "url": "https://www.sec.gov/newsroom/whats-new",
                                "snippet": "ignore",
                                "date": "2026-03-13",
                            },
                            {
                                "title": "Home",
                                "url": "https://www.sec.gov",
                                "snippet": "ignore",
                                "date": "2026-03-13",
                            },
                            {
                                "title": "EDGAR Filing Documents for 0001213900-26-025216 - SEC.gov",
                                "url": "https://www.sec.gov/Archives/edgar/data/1396092/000121390026025216/0001213900-26-025216-index.htm",
                                "snippet": "ignore",
                                "date": "2026-03-13",
                            },
                            {
                                "title": "SEC approves new filing update for spot bitcoin ETFs",
                                "url": "https://www.sec.gov/newsroom/press-releases/2026-42",
                                "snippet": "SEC press release",
                                "date": "2026-03-13",
                            },
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(items) == 1
    assert items[0].url == "https://www.sec.gov/newsroom/press-releases/2026-42"


def test_parse_results_filters_fed_index_pages_but_keeps_speech_pages():
    topic = ps.SearchTopic(
        name="macro",
        query="macro query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "News & Events - Federal Reserve Board",
                    "url": "https://www.federalreserve.gov/newsevents.htm",
                    "snippet": "Index page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "2026 Press Releases - Federal Reserve Board",
                    "url": "https://www.federalreserve.gov/newsevents/pressreleases/2026-press.htm",
                    "snippet": "Year listing.",
                    "date": "2026-03-13",
                },
                {
                    "title": "Fed official says inflation progress remains uneven",
                    "url": "https://www.federalreserve.gov/newsevents/speech/waller20260313a.htm",
                    "snippet": "A valid speech page.",
                    "date": "2026-03-13",
                },
            ]
        },
        topic=topic,
    )

    assert len(items) == 1
    assert items[0].url == "https://www.federalreserve.gov/newsevents/speech/waller20260313a.htm"


def test_parse_results_does_not_filter_broadcom_pages_after_ai_bigtech_removal():
    topic = ps.SearchTopic(
        name="us_equity",
        query="equity query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Latest News & Stories - Broadcom",
                    "url": "https://news.broadcom.com/latest",
                    "snippet": "Landing page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "Technologies - Broadcom News and Stories",
                    "url": "https://news.broadcom.com/category/technologies",
                    "snippet": "Category page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "Broadcom launches new optical interconnect platform",
                    "url": "https://news.broadcom.com/releases/broadcom-launches-new-optical-interconnect-platform",
                    "snippet": "A valid release page.",
                    "date": "2026-03-13",
                },
            ]
        },
        topic=topic,
    )

    assert len(items) == 3


def test_parse_results_filters_reuters_quote_and_topic_index_pages():
    equity_topic = ps.SearchTopic(
        name="us_equity",
        query="equity query",
        retry_query="",
    )

    equity_items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "NVDA.O - | Stock Price & Latest News",
                    "url": "https://www.reuters.com/markets/companies/NVDA.O",
                    "snippet": "Quote page.",
                    "date": "2026-03-13",
                }
            ]
        },
        topic=equity_topic,
    )

    assert equity_items == []


def test_parse_results_filters_bitcoin_etf_product_pages():
    topic = ps.SearchTopic(
        name="bitcoin",
        query="bitcoin query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "iShares Ethereum Trust ETF | ETHA",
                    "url": "https://www.ishares.com/us/products/337614/ishares-ethereum-trust-etf",
                    "snippet": "Wrong ETF product page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "iShares Bitcoin Trust ETF | IBIT",
                    "url": "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf",
                    "snippet": "Issuer product page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "Bitwise Bitcoin ETF | BITB",
                    "url": "https://www.bitbetf.com/fund/bitb",
                    "snippet": "Issuer fund page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "Bitcoin ETF inflows stay firm as issuers add assets",
                    "url": "https://www.reuters.com/world/us/bitcoin-etf-inflows-stay-firm-2026-03-13/",
                    "snippet": "A valid market article.",
                    "date": "2026-03-13",
                },
            ]
        },
        topic=topic,
    )

    assert len(items) == 1
    assert (
        items[0].url == "https://www.reuters.com/world/us/bitcoin-etf-inflows-stay-firm-2026-03-13/"
    )


def test_parse_results_filters_sec_newsroom_listings_for_bitcoin():
    topic = ps.SearchTopic(
        name="bitcoin",
        query="bitcoin query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Press Releases - SEC.gov",
                    "url": "https://www.sec.gov/newsroom/press-releases",
                    "snippet": "Listing page.",
                    "date": "2026-03-13",
                },
                {
                    "title": "SEC updates timeline for spot bitcoin ETF filing review",
                    "url": "https://www.sec.gov/newsroom/press-releases/2026-42",
                    "snippet": "Valid press release.",
                    "date": "2026-03-13",
                },
            ]
        },
        topic=topic,
    )

    assert len(items) == 1
    assert items[0].url == "https://www.sec.gov/newsroom/press-releases/2026-42"


def test_parse_results_filters_sec_taxonomy_notice_and_meta_news_root():
    bitcoin_topic = ps.SearchTopic(
        name="bitcoin",
        query="bitcoin query",
        retry_query="",
    )

    bitcoin_items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Notice | U.S. Securities and Exchange Commission - SEC.gov",
                    "url": "https://www.sec.gov/taxonomy/term/193086",
                    "snippet": "Taxonomy notice page.",
                    "date": "2026-03-13",
                }
            ]
        },
        topic=bitcoin_topic,
    )

    assert bitcoin_items == []


def test_fetch_news_from_perplexity_records_raw_candidates_when_everything_is_filtered(
    monkeypatch, tmp_path
):
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Reuters Service Status",
                                "url": "https://status.reuters.com",
                                "snippet": "ignore",
                                "date": "2026-03-13",
                            }
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert items == []
    events = [event for event in observer.events if event["event"] == "perplexity_items_collected"]
    assert len(events) == 1
    assert events[0]["reason"] == "filtered_all"
    assert events[0]["raw_items"][0]["url"] == "https://status.reuters.com"


def test_search_once_exposes_status_details(monkeypatch):
    client = _Client([_StatusError(401, "invalid api key")], [])

    try:
        ps._search_once(
            client=client,
            query="macro query",
            recency_filter="day",
        )
    except HttpFetchError as exc:
        assert "status=401" in str(exc)
        assert "invalid api key" in str(exc)
    else:
        raise AssertionError("HttpFetchError was expected")


def test_search_once_retries_timeout_with_provider_backoff(monkeypatch):
    calls: list[dict] = []
    sleeps: list[float] = []
    now = {"value": 100.0}
    client = _Client(
        [
            _TimeoutError(),
            _SDKResponse(
                {
                    "results": [
                        {
                            "title": "Fed keeps options open",
                            "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                            "snippet": "The Fed kept its options open.",
                            "date": "2026-03-13T01:00:00Z",
                        }
                    ]
                }
            ),
        ],
        calls,
    )

    monkeypatch.setattr(provider_runtime.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        provider_runtime.time,
        "sleep",
        lambda seconds: sleeps.append(seconds) or now.__setitem__("value", now["value"] + seconds),
    )
    monkeypatch.setattr(provider_runtime.random, "random", lambda: 0.5)

    payload, usage, usage_present = ps._search_once(
        client=client,
        query="macro query",
        recency_filter="day",
    )

    assert len(calls) == 2
    assert payload["results"][0]["title"] == "Fed keeps options open"
    assert usage["input_tokens"] is None
    assert usage_present is False
    assert sleeps and round(sleeps[0], 2) == 1.5


def test_fetch_news_from_perplexity_records_usage_and_topic_audit(monkeypatch, tmp_path):
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Fed keeps options open",
                                "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                                "snippet": "The Fed kept its options open.",
                                "date": "2026-03-13T01:00:00Z",
                            }
                        ]
                    },
                    usage={
                        "prompt_tokens": 123,
                        "completion_tokens": 45,
                        "input_tokens_details": {"cached_tokens": 7},
                    },
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert len(items) == 1
    assert observer.provider_usage["perplexity"].requests == 1
    assert observer.provider_usage["perplexity"].response_sources == 1
    assert observer.provider_usage["perplexity"].input_tokens == 123
    assert observer.provider_usage["perplexity"].output_tokens == 45
    assert observer.provider_usage["perplexity"].cached_input_tokens == 7
    assert observer.perplexity_topic_audit["macro"]["candidate_urls"] == [
        "https://www.reuters.com/world/us/fed-keeps-options-open"
    ]
    events = [event for event in observer.events if event["event"] == "perplexity_items_collected"]
    assert len(events) == 1
    assert events[0]["topic"] == "macro"
    assert events[0]["count"] == 1
    assert events[0]["items"][0]["title"] == "Fed keeps options open"
    assert events[0]["items"][0]["url"] == "https://www.reuters.com/world/us/fed-keeps-options-open"
    assert events[0]["items"][0]["domain"] == "reuters.com"
    assert "collected_at" in events[0]["items"][0]


def test_fetch_news_from_perplexity_reads_usage_from_model_extra(monkeypatch, tmp_path):
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Fed keeps options open",
                                "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                                "snippet": "The Fed kept its options open.",
                                "date": "2026-03-13T01:00:00Z",
                            }
                        ]
                    },
                    model_extra={
                        "usage": {
                            "input_tokens": 210,
                            "output_tokens": 55,
                            "input_tokens_details": {
                                "cache_read_input_tokens": 11,
                            },
                        }
                    },
                )
            ],
            [],
        ),
    )

    ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    usage = observer.provider_usage["perplexity"]
    assert usage.input_tokens == 210
    assert usage.output_tokens == 55
    assert usage.cached_input_tokens == 11
    assert usage.usage_parse_failures == 0


def test_fetch_news_from_perplexity_leaves_token_usage_null_when_usage_missing(
    monkeypatch, tmp_path
):
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Fed keeps options open",
                                "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                                "snippet": "The Fed kept its options open.",
                                "date": "2026-03-13T01:00:00Z",
                            }
                        ]
                    }
                )
            ],
            [],
        ),
    )

    ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    usage = observer.provider_usage["perplexity"]
    assert usage.requests == 1
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.cached_input_tokens is None
    assert usage.usage_parse_failures == 0
    assert not [event for event in observer.events if event["event"] == "provider_usage_unparsed"]


def test_fetch_news_from_perplexity_records_empty_reason(monkeypatch, tmp_path):
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="macro",
                query="macro query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client([_SDKResponse({"results": []})], []),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert items == []
    events = [event for event in observer.events if event["event"] == "perplexity_items_collected"]
    assert len(events) == 1
    assert events[0]["topic"] == "macro"
    assert events[0]["count"] == 0
    assert events[0]["items"] == []
    assert events[0]["reason"] == "api_empty"


def test_parse_results_filters_ft_market_data_pages():
    topic = ps.SearchTopic(
        name="us_equity",
        query="equity query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Markets data - stock market, bond, equity, commodity prices - FT.com",
                    "url": "https://markets.ft.com/data/equities/tearsheet/summary?s=DJI:DJI",
                    "snippet": "Not a news story.",
                    "date": "2026-03-13T01:00:00Z",
                },
                {
                    "title": "Meta Platforms Inc, FB2A:FRA Summary - FT.com",
                    "url": "https://www.ft.com/content/summary?foo=bar",
                    "snippet": "Still not a news story.",
                    "date": "2026-03-13T01:00:00Z",
                },
            ]
        },
        topic=topic,
    )

    assert items == []


def test_parse_results_filters_apple_and_non_english_results():
    topic = ps.SearchTopic(
        name="us_equity",
        query="ai query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Apple Podcasts episode on AI markets",
                    "url": "https://podcasts.apple.com/us/podcast/some-show/id123",
                    "snippet": "Podcast listing.",
                    "date": "2026-03-13T01:00:00Z",
                },
                {
                    "title": "中国市场对比特币ETF反应",
                    "url": "https://cn.wsj.com/articles/bitcoin-etf",
                    "snippet": "Non-English news.",
                    "date": "2026-03-13T01:00:00Z",
                },
                {
                    "title": "TV episode recap",
                    "url": "https://tv.apple.com/us/show/some-program",
                    "snippet": "Not a news article.",
                    "date": "2026-03-13T01:00:00Z",
                },
            ]
        },
        topic=topic,
    )

    assert items == []


def test_parse_results_accepts_ft_article_paths():
    topic = ps.SearchTopic(
        name="macro",
        query="macro query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Fed outlook keeps bond investors cautious",
                    "url": "https://www.ft.com/content/abcd1234",
                    "snippet": "A valid FT article.",
                    "date": "2026-03-13T01:00:00Z",
                }
            ]
        },
        topic=topic,
    )

    assert len(items) == 1
    assert items[0].url == "https://www.ft.com/content/abcd1234"


def test_fetch_news_from_perplexity_logs_filtered_empty_results(monkeypatch, tmp_path):
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="us_equity",
                query="equity query",
                retry_query="",
            ),
        ),
    )
    monkeypatch.setattr(
        ps,
        "_build_client",
        lambda api_key: _Client(
            [
                _SDKResponse(
                    {
                        "results": [
                            {
                                "title": "Dow Jones Industrial Average, DJI:DJI Summary - FT.com",
                                "url": "https://markets.ft.com/data/indices/tearsheet/summary?s=DJI:DJI",
                                "snippet": "Bad FT data page.",
                                "date": "2026-03-13T01:00:00Z",
                            }
                        ]
                    }
                )
            ],
            [],
        ),
    )

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert items == []
    collected_events = [
        event for event in observer.events if event["event"] == "perplexity_items_collected"
    ]
    assert collected_events[0]["reason"] == "filtered_all"
    filter_events = [
        event for event in observer.events if event["event"] == "perplexity_result_filter_empty"
    ]
    assert len(filter_events) == 1
    assert filter_events[0]["topic"] == "us_equity"
    assert filter_events[0]["raw_result_count"] == 1


def test_parse_results_filters_short_titles():
    topic = ps.SearchTopic(
        name="macro",
        query="macro query",
        retry_query="",
    )

    items = ps._parse_results(
        payload={
            "results": [
                {
                    "title": "Fed move",
                    "url": "https://www.reuters.com/world/us/fed-move",
                    "snippet": "Too short.",
                    "date": "2026-03-13T01:00:00Z",
                }
            ]
        },
        topic=topic,
    )

    assert items == []
