from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.sources.asset_news_publisher import (
    _item_to_rows,
    publish_asset_news,
)
from morning_brief.models import NewsItem


def _item(**overrides: object) -> NewsItem:
    defaults: dict = {
        "title": "Ethereum rallies past resistance",
        "url": "https://example.com/eth",
        "source": "Cointelegraph",
        "published_at": datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc),
        "topic": "eth",
        "provider": "newsdata_io",
        "summary": "ETH breaks key level.",
    }
    defaults.update(overrides)
    return NewsItem(**defaults)


def test_item_to_rows_maps_single_coin() -> None:
    rows = _item_to_rows(_item())
    assert rows == [
        {
            "symbol": "ETHUSDT",
            "title": "Ethereum rallies past resistance",
            "url": "https://example.com/eth",
            "source": "Cointelegraph",
            "published_at": "2026-08-03T08:00:00+00:00",
            "summary": "ETH breaks key level.",
        }
    ]


def test_item_to_rows_duplicates_per_multi_coin_article() -> None:
    rows = _item_to_rows(_item(topic="eth,sol"))
    assert {r["symbol"] for r in rows} == {"ETHUSDT", "SOLUSDT"}


def test_item_to_rows_drops_btc_only_articles() -> None:
    assert _item_to_rows(_item(topic="btc")) == []


def test_item_to_rows_drops_items_missing_title_or_url() -> None:
    assert _item_to_rows(_item(title="")) == []
    assert _item_to_rows(_item(url="")) == []


def test_publish_asset_news_skips_without_supabase_config() -> None:
    count = publish_asset_news([_item()], supabase_url="", service_role_key="")
    assert count == 0


def test_publish_asset_news_skips_when_no_matching_items() -> None:
    count = publish_asset_news(
        [_item(topic="btc")],
        supabase_url="https://example.supabase.co",
        service_role_key="key",
    )
    assert count == 0


def test_publish_asset_news_upserts_matched_rows(monkeypatch) -> None:
    captured: dict = {}

    class _FakeTable:
        def upsert(self, rows, on_conflict):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self

        def execute(self):
            return None

    class _FakeClient:
        def table(self, name):
            captured["table"] = name
            return _FakeTable()

    import morning_brief.data.sources.asset_news_publisher as mod

    monkeypatch.setattr(mod, "_get_supabase_client", lambda *a, **k: _FakeClient())

    count = publish_asset_news(
        [_item(), _item(url="https://example.com/sol", topic="sol")],
        supabase_url="https://example.supabase.co",
        service_role_key="key",
    )

    assert count == 2
    assert captured["table"] == "arena_asset_news"
    assert captured["on_conflict"] == "symbol,url"
    assert {r["symbol"] for r in captured["rows"]} == {"ETHUSDT", "SOLUSDT"}


def test_publish_asset_news_graceful_on_client_error(monkeypatch) -> None:
    import morning_brief.data.sources.asset_news_publisher as mod

    # client가 .table()이 없는 객체를 반환해도(예: 초기화는 됐지만 호출 시 예외)
    # publish_asset_news가 이를 삼키고 0을 반환해야 본 파이프라인이 안전하다.
    monkeypatch.setattr(mod, "_get_supabase_client", lambda *a, **k: object())

    count = publish_asset_news(
        [_item()], supabase_url="https://example.supabase.co", service_role_key="key"
    )
    assert count == 0
