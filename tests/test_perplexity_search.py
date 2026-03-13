from __future__ import annotations

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
    def __init__(self, payload):
        self._payload = payload

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
                domain_filter=("reuters.com", "federalreserve.gov"),
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
    assert calls[0]["search_domain_filter"] == ["reuters.com", "federalreserve.gov"]
    assert calls[0]["max_results"] == ps.SEARCH_MAX_RESULTS
    assert "search_mode" not in calls[0]
    assert items[0].source == "Reuters"
    assert items[0].provider == "perplexity_search"
    assert items[0].topic == "macro"
    assert items[0].summary == "The Fed kept its options open."
    assert items[0].citations == ["https://www.reuters.com/world/us/fed-keeps-options-open"]


def test_fetch_news_from_perplexity_retries_with_topic_retry_query(monkeypatch):
    calls = []

    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="bitcoin",
                query="bitcoin query",
                retry_query="bitcoin retry",
                domain_filter=("coindesk.com",),
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
    assert len(items) == 2
    assert items[0].topic == "bitcoin"
    assert items[1].why_it_matters


def test_fetch_news_from_perplexity_filters_unallowed_domain(monkeypatch):
    monkeypatch.setattr(
        ps,
        "TOPIC_SPECS",
        (
            ps.SearchTopic(
                name="us_equity",
                query="equity query",
                retry_query="",
                domain_filter=("reuters.com",),
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
                                "title": "Bad source",
                                "url": "https://example.com/market-story",
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


def test_search_once_exposes_status_details(monkeypatch):
    client = _Client([_StatusError(401, "invalid api key")], [])

    try:
        ps._search_once(
            client=client,
            query="macro query",
            domain_filter=("reuters.com",),
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

    payload = ps._search_once(
        client=client,
        query="macro query",
        domain_filter=("reuters.com",),
        recency_filter="day",
    )

    assert len(calls) == 2
    assert payload["results"][0]["title"] == "Fed keeps options open"
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
                domain_filter=("reuters.com",),
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

    items = ps.fetch_news_from_perplexity(
        max_items=5,
        api_key="pplx-test-key",
        observer=observer,
    )

    assert len(items) == 1
    assert observer.provider_usage["perplexity"].requests == 1
    assert observer.provider_usage["perplexity"].response_sources == 1
    assert observer.perplexity_topic_audit["macro"]["candidate_urls"] == [
        "https://www.reuters.com/world/us/fed-keeps-options-open"
    ]
