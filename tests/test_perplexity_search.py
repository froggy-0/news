from __future__ import annotations

from morning_brief.data.sources import perplexity_search as ps
from morning_brief.data.sources.http_client import HttpFetchError


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
