from __future__ import annotations

from datetime import datetime, timezone

import pytest

from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.thenewsapi_provider import fetch_thenewsapi_page


def test_fetch_thenewsapi_page_normalizes_results(monkeypatch):
    captured: dict[str, object] = {}

    def fake_get_json_with_retry(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {
            "success": True,
            "data": {
                "next": None,
                "results": [
                    {
                        "title": "Bitcoin ETF flows stay positive",
                        "url": "https://www.coindesk.com/markets/2026/03/13/bitcoin-etf-flows-stay-positive",
                        "source": {"name": "CoinDesk", "domain": "coindesk.com"},
                        "category": "markets",
                        "published_at": "2026-03-13T01:23:45Z",
                        "summary": "ETF demand remains firm.",
                        "description": "Institutional demand remains firm.",
                    }
                ],
            },
        }

    monkeypatch.setattr(
        "morning_brief.data.sources.thenewsapi_provider.get_json_with_retry",
        fake_get_json_with_retry,
    )

    page = fetch_thenewsapi_page(
        api_key="test-key",
        max_items=6,
        lookback_hours=36,
        langs="en",
        categories="markets,policy",
        query="bitcoin",
    )

    assert captured["url"] == "https://api.thenewsapi.net/crypto"
    assert captured["params"]["size"] == 6
    assert captured["params"]["langs"] == "en"
    assert captured["params"]["categories"] == "markets,policy"
    assert page.has_next is False
    assert len(page.items) == 1
    assert page.items[0].provider == "thenewsapi"
    assert page.items[0].source == "CoinDesk"
    assert page.items[0].topic == "bitcoin"
    assert page.items[0].summary == "ETF demand remains firm."
    assert page.items[0].published_at == datetime(2026, 3, 13, 1, 23, 45, tzinfo=timezone.utc)


def test_fetch_thenewsapi_page_caps_free_plan_size(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "morning_brief.data.sources.thenewsapi_provider.get_json_with_retry",
        lambda url, **kwargs: (
            captured.update(kwargs) or {"success": True, "data": {"next": None, "results": []}}
        ),
    )

    page = fetch_thenewsapi_page(
        api_key="test-key",
        max_items=20,
        lookback_hours=36,
        langs="en",
        categories="markets",
        query="bitcoin",
    )

    assert captured["params"]["size"] == 10
    assert page.requested_size == 10


def test_fetch_thenewsapi_page_raises_for_invalid_shape(monkeypatch):
    monkeypatch.setattr(
        "morning_brief.data.sources.thenewsapi_provider.get_json_with_retry",
        lambda *args, **kwargs: {"success": True, "data": {"results": {}}},
    )

    with pytest.raises(HttpFetchError):
        fetch_thenewsapi_page(
            api_key="test-key",
            max_items=6,
            lookback_hours=36,
            langs="en",
            categories="markets",
            query="bitcoin",
        )
