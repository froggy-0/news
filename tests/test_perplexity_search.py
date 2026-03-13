from __future__ import annotations

from morning_brief.data.sources import perplexity_search as ps


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


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
    monkeypatch.setattr(ps, "is_host_resolvable", lambda *_: True)

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response(
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

    monkeypatch.setattr(ps.requests, "post", fake_post)

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert len(calls) == 1
    assert calls[0]["url"] == ps.SEARCH_API_URL
    assert calls[0]["json"]["query"] == "macro query"
    assert calls[0]["json"]["search_domain_filter"] == ["reuters.com", "federalreserve.gov"]
    assert calls[0]["json"]["max_results"] == ps.SEARCH_MAX_RESULTS
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
    monkeypatch.setattr(ps, "is_host_resolvable", lambda *_: True)

    payloads = [
        {
            "results": [
                {
                    "title": "ETF flow stays positive",
                    "url": "https://www.coindesk.com/markets/2026/03/13/etf-flow-stays-positive/",
                    "snippet": "ETF flow stayed positive overnight.",
                    "date": "2026-03-13",
                }
            ]
        },
        {
            "results": [
                {
                    "title": "Bitcoin regulation stays in focus",
                    "url": "https://www.coindesk.com/policy/2026/03/13/bitcoin-regulation-stays-in-focus/",
                    "snippet": "Regulation remained a focus.",
                    "date": "2026-03-13T02:00:00Z",
                }
            ]
        },
    ]

    def fake_post(url, headers, json, timeout):
        calls.append(json["query"])
        return _Response(payloads[len(calls) - 1])

    monkeypatch.setattr(ps.requests, "post", fake_post)

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert calls == ["bitcoin query", "bitcoin retry"]
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
    monkeypatch.setattr(ps, "is_host_resolvable", lambda *_: True)
    monkeypatch.setattr(
        ps.requests,
        "post",
        lambda url, headers, json, timeout: _Response(
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
        ),
    )

    items = ps.fetch_news_from_perplexity(max_items=5, api_key="pplx-test-key")

    assert items == []
