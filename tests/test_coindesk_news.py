from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data import providers
from morning_brief.data.sources.coindesk_news import fetch_coindesk_news


def test_fetch_coindesk_news_pages_latest_first_and_stops_at_lookback(monkeypatch):
    calls: list[dict[str, object]] = []
    responses = [
        {
            "Data": [
                {
                    "ID": "3",
                    "TITLE": "Bitcoin ETF demand rises",
                    "URL": "https://www.coindesk.com/markets/bitcoin-etf-demand-rises",
                    "BODY": "ETF flow details",
                    "PUBLISHED_ON": 1_700_007_200,
                },
                {
                    "ID": "2",
                    "TITLE": "Bitcoin miners rally",
                    "URL": "https://www.coindesk.com/markets/bitcoin-miners-rally",
                    "BODY": "Mining equity details",
                    "PUBLISHED_ON": 1_700_003_600,
                },
            ]
        },
        {
            "Data": [
                {
                    "ID": "1",
                    "TITLE": "Old bitcoin market note",
                    "URL": "https://www.coindesk.com/markets/old-bitcoin-market-note",
                    "BODY": "Older details",
                    "PUBLISHED_ON": 1_699_900_000,
                }
            ]
        },
    ]

    def fake_get_json(url, *, params, **kwargs):
        calls.append(params)
        return responses[len(calls) - 1]

    monkeypatch.setattr(
        "morning_brief.data.sources.coindesk_news.get_json_with_retry",
        fake_get_json,
    )

    items = fetch_coindesk_news(
        max_items=5,
        lookback_hours=4,
        now=datetime.fromtimestamp(1_700_010_000, tz=timezone.utc),
    )

    assert [item.title for item in items] == [
        "Bitcoin ETF demand rises",
        "Bitcoin miners rally",
    ]
    assert all(item.provider == providers.COINDESK_API for item in items)
    assert calls[0]["to_ts"] == 1_700_010_000
    assert calls[1]["to_ts"] == 1_700_003_599


def test_fetch_coindesk_news_deduplicates_by_id_and_url(monkeypatch):
    payload = {
        "Data": [
            {
                "ID": "1",
                "TITLE": "Bitcoin ETF demand rises",
                "URL": "https://www.coindesk.com/markets/bitcoin-etf-demand-rises",
                "BODY": "First",
                "PUBLISHED_ON": 1_700_007_200,
            },
            {
                "ID": "1",
                "TITLE": "Bitcoin ETF demand rises duplicate",
                "URL": "https://www.coindesk.com/markets/bitcoin-etf-demand-rises",
                "BODY": "Duplicate",
                "PUBLISHED_ON": 1_700_007_100,
            },
        ]
    }

    calls = 0

    def fake_get_json(*_, **__):
        nonlocal calls
        calls += 1
        return payload if calls == 1 else {"Data": []}

    monkeypatch.setattr(
        "morning_brief.data.sources.coindesk_news.get_json_with_retry",
        fake_get_json,
    )

    items = fetch_coindesk_news(
        max_items=5,
        lookback_hours=4,
        now=datetime.fromtimestamp(1_700_010_000, tz=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].title == "Bitcoin ETF demand rises"
    assert items[0].citations == ["https://www.coindesk.com/markets/bitcoin-etf-demand-rises"]
