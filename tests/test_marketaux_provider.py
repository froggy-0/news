from __future__ import annotations

from datetime import datetime, timezone

import pytest

from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.marketaux_provider import fetch_marketaux_page


def test_fetch_marketaux_page_normalizes_results(monkeypatch):
    captured: dict[str, object] = {}

    def fake_get_json_with_retry(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {
            "meta": {
                "found": 3,
                "returned": 3,
                "limit": 3,
                "page": 1,
            },
            "data": [
                {
                    "title": "Bitcoin ETF flows stay positive",
                    "url": "https://www.reuters.com/world/us/bitcoin-etf-flows-stay-positive",
                    "source": "reuters.com",
                    "published_at": "2026-03-13T01:23:45.000000Z",
                    "description": "ETF demand remains firm.",
                    "snippet": "Institutional demand remains firm.",
                }
            ],
        }

    monkeypatch.setattr(
        "morning_brief.data.sources.marketaux_provider.get_json_with_retry",
        fake_get_json_with_retry,
    )

    page = fetch_marketaux_page(
        api_key="test-key",
        max_items=3,
        lookback_hours=36,
        language="en",
        domains="reuters.com,cnbc.com",
        search="bitcoin",
    )

    assert captured["url"] == "https://api.marketaux.com/v1/news/all"
    assert captured["params"]["limit"] == 3
    assert captured["params"]["language"] == "en"
    assert captured["params"]["domains"] == "reuters.com,cnbc.com"
    assert captured["params"]["sort"] == "published_at"
    assert page.has_next is False
    assert len(page.items) == 1
    assert page.items[0].provider == "marketaux"
    assert page.items[0].source == "reuters.com"
    assert page.items[0].topic == "bitcoin"
    assert page.items[0].published_at == datetime(2026, 3, 13, 1, 23, 45, tzinfo=timezone.utc)


def test_fetch_marketaux_page_caps_free_plan_limit(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "morning_brief.data.sources.marketaux_provider.get_json_with_retry",
        lambda url, **kwargs: (
            captured.update(kwargs)
            or {"meta": {"found": 0, "returned": 0, "limit": 3, "page": 1}, "data": []}
        ),
    )

    page = fetch_marketaux_page(
        api_key="test-key",
        max_items=10,
        lookback_hours=36,
        language="en",
        domains="reuters.com",
        search="bitcoin",
    )

    assert captured["params"]["limit"] == 3
    assert page.requested_limit == 3


def test_fetch_marketaux_page_raises_for_invalid_shape(monkeypatch):
    monkeypatch.setattr(
        "morning_brief.data.sources.marketaux_provider.get_json_with_retry",
        lambda *args, **kwargs: {"meta": {}, "data": {}},
    )

    with pytest.raises(HttpFetchError):
        fetch_marketaux_page(
            api_key="test-key",
            max_items=3,
            lookback_hours=36,
            language="en",
            domains="reuters.com",
            search="bitcoin",
        )
