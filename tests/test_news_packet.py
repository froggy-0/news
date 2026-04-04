"""NewsPacketItem TypedDict 및 news_items_to_packet 검증."""

from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.news_packet import NewsPacketItem, news_items_to_packet
from morning_brief.models import NewsItem

_NEWS_PACKET_ITEM_KEYS = {
    "title",
    "url",
    "source",
    "published_at",
    "domain",
    "source_tier",
    "preferred_source",
    "age_hours",
    "topic",
    "provider",
    "summary",
    "why_it_matters",
    "citations",
    "official_source",
}


def _make_item(**kwargs: object) -> NewsItem:
    defaults: dict[str, object] = {
        "title": "Test Title",
        "url": "https://reuters.com/article/test",
        "source": "Reuters",
        "published_at": datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        "topic": "macro",
        "provider": "perplexity_search",
        "summary": "Test summary",
        "why_it_matters": "Test impact",
        "citations": [],
    }
    defaults.update(kwargs)
    return NewsItem(**defaults)  # type: ignore[arg-type]


def test_news_items_to_packet_returns_all_14_keys() -> None:
    items = [_make_item()]
    packet = news_items_to_packet(items)
    assert len(packet) == 1
    assert set(packet[0].keys()) == _NEWS_PACKET_ITEM_KEYS


def test_news_items_to_packet_published_at_none_gives_age_hours_none() -> None:
    item = _make_item(published_at=None)
    packet = news_items_to_packet([item])
    assert packet[0]["age_hours"] is None


def test_news_items_to_packet_published_at_set_gives_age_hours() -> None:
    item = _make_item(published_at=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc))
    packet = news_items_to_packet([item])
    assert packet[0]["age_hours"] is not None
    assert isinstance(packet[0]["age_hours"], float)


def test_news_items_to_packet_official_source_flag() -> None:
    official = _make_item(provider="grok_official_x")
    non_official = _make_item(provider="perplexity_search")
    packet = news_items_to_packet([official, non_official])
    assert packet[0]["official_source"] is True
    assert packet[1]["official_source"] is False


def test_news_packet_item_is_typeddict() -> None:
    """NewsPacketItem이 TypedDict 서브클래스임을 확인한다."""
    import typing

    assert issubclass(NewsPacketItem, dict)
    hints = typing.get_type_hints(NewsPacketItem)
    assert set(hints.keys()) == _NEWS_PACKET_ITEM_KEYS


def test_packet_item_get_access_still_works() -> None:
    """하위 호환: TypedDict는 dict이므로 .get() 접근도 정상 동작해야 한다."""
    items = [_make_item()]
    packet = news_items_to_packet(items)
    item = packet[0]
    assert item.get("title") == item["title"]
    assert item.get("nonexistent_key") is None
