from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.sources.newsdata_provider import fetch_newsdata_crypto_news


def test_fetch_newsdata_crypto_news_normalizes_results(monkeypatch):
    captured: dict[str, object] = {}

    def fake_get_json_with_retry(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {
            "status": "success",
            "totalResults": 1,
            "results": [
                {
                    "article_id": "abc123",
                    "link": "https://cointelegraph.com/news/eth-rally",
                    "title": "Ethereum rallies past resistance",
                    "description": "ETH breaks key level amid renewed demand.",
                    "coin": ["ETH"],
                    "source_name": "Cointelegraph",
                    "source_id": "cointelegraph",
                    "pubDate": "2026-07-31 08:00:00",
                }
            ],
            "nextPage": None,
        }

    monkeypatch.setattr(
        "morning_brief.data.sources.newsdata_provider.get_json_with_retry",
        fake_get_json_with_retry,
    )

    items = fetch_newsdata_crypto_news(
        api_key="test-key",
        max_items=10,
        lookback_hours=36,
        coins="BTC,ETH,SOL",
        # pubDate가 "2026-07-31 08:00:00"으로 고정돼 있어, now를 실제 시각(wall clock)에
        # 맡기면 36시간 lookback 밖으로 밀려나 items가 빈 리스트가 되는 시한부 버그가 있었다
        # (CI에서 2026-08-01 이후 계속 실패). now를 기사와 같은 시각대로 고정해 시간에
        # 의존하지 않게 한다.
        now=datetime(2026, 7, 31, 8, 30, 0, tzinfo=timezone.utc),
    )

    assert captured["url"] == "https://newsdata.io/api/1/crypto"
    assert captured["params"]["apikey"] == "test-key"
    assert captured["params"]["coin"] == "BTC,ETH,SOL"
    assert captured["params"]["size"] == 10
    # 무료 플랜은 from_date/to_date를 422로 거부함(실측) — 절대 보내지 않아야 함
    assert "from_date" not in captured["params"]
    assert "to_date" not in captured["params"]
    assert len(items) == 1
    item = items[0]
    assert item.provider == "newsdata_io"
    assert item.url == "https://cointelegraph.com/news/eth-rally"
    assert item.topic == "eth"
    assert item.published_at == datetime(2026, 7, 31, 8, 0, 0, tzinfo=timezone.utc)


def test_fetch_newsdata_crypto_news_caps_free_plan_size(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "morning_brief.data.sources.newsdata_provider.get_json_with_retry",
        lambda url, **kwargs: (
            captured.update(kwargs) or {"status": "success", "results": [], "nextPage": None}
        ),
    )

    fetch_newsdata_crypto_news(api_key="test-key", max_items=50, lookback_hours=36)

    assert captured["params"]["size"] == 10


def test_fetch_newsdata_crypto_news_returns_empty_without_api_key():
    items = fetch_newsdata_crypto_news(api_key="", max_items=10, lookback_hours=36)
    assert items == []


def test_fetch_newsdata_crypto_news_degrades_gracefully_on_error(monkeypatch):
    from morning_brief.data.sources.http_client import HttpFetchError

    def fake_get_json_with_retry(url: str, **kwargs):
        raise HttpFetchError("HTTP 401 응답을 받았어요", status_code=401, provider="newsdata_io")

    monkeypatch.setattr(
        "morning_brief.data.sources.newsdata_provider.get_json_with_retry",
        fake_get_json_with_retry,
    )

    items = fetch_newsdata_crypto_news(api_key="bad-key", max_items=10, lookback_hours=36)
    assert items == []


def test_fetch_newsdata_crypto_news_degrades_on_status_error(monkeypatch):
    monkeypatch.setattr(
        "morning_brief.data.sources.newsdata_provider.get_json_with_retry",
        lambda url, **kwargs: {"status": "error", "results": {"message": "invalid"}},
    )

    items = fetch_newsdata_crypto_news(api_key="test-key", max_items=10, lookback_hours=36)
    assert items == []


def test_fetch_newsdata_crypto_news_filters_stale_items_client_side(monkeypatch):
    # 무료 플랜은 from_date/to_date를 못 쓰므로 lookback_hours는 응답을 받은 뒤
    # published_at 기준으로 직접 걸러내야 한다.
    stale = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    fresh = datetime(2026, 7, 31, 6, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "morning_brief.data.sources.newsdata_provider.get_json_with_retry",
        lambda url, **kwargs: {
            "status": "success",
            "results": [
                {
                    "link": "https://example.com/stale",
                    "title": "Stale article",
                    "coin": ["BTC"],
                    "pubDate": stale.strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "link": "https://example.com/fresh",
                    "title": "Fresh article",
                    "coin": ["BTC"],
                    "pubDate": fresh.strftime("%Y-%m-%d %H:%M:%S"),
                },
            ],
        },
    )

    items = fetch_newsdata_crypto_news(
        api_key="test-key",
        max_items=10,
        lookback_hours=36,
        now=datetime(2026, 7, 31, 8, 0, 0, tzinfo=timezone.utc),
    )

    assert [item.url for item in items] == ["https://example.com/fresh"]


def test_fetch_newsdata_crypto_news_skips_items_without_url():
    # url(link) 없는 아이템은 버려야 함(모든 provider 공통 규약)
    from morning_brief.data.sources.newsdata_provider import _article_to_news_item

    assert _article_to_news_item({"title": "no link here"}) is None
    assert _article_to_news_item({"title": "", "link": "https://x.com"}) is None
