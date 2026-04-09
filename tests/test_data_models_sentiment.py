"""데이터 모델 sentiment 필드 테스트 (Req 2.1~2.3, 5.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.news_packet import news_items_to_packet
from morning_brief.data.sources.grok_x_keyword import XSignal, x_signals_to_dict
from morning_brief.models import NewsItem


def test_news_item_default_sentiment_fields() -> None:
    item = NewsItem(title="t", url="u", source="s", published_at=None)
    assert item.sentiment_score is None
    assert item.sentiment_label == ""
    assert item.sentiment_confidence is None


def test_xsignal_default_sentiment_fields_and_existing_sentiment() -> None:
    sig = XSignal(headline="h", summary="s", why_it_matters="w")
    assert sig.sentiment == "neutral"  # 기존 Grok 라벨 유지
    assert sig.sentiment_score is None
    assert sig.sentiment_confidence is None


def test_x_signals_to_dict_includes_sentiment_fields() -> None:
    sig = XSignal(
        headline="h",
        summary="s",
        why_it_matters="w",
        sentiment="bullish",
        sentiment_score=0.75,
        sentiment_confidence=0.88,
    )
    dicts = x_signals_to_dict([sig])
    assert dicts[0]["sentiment_score"] == 0.75
    assert dicts[0]["sentiment_confidence"] == 0.88
    assert dicts[0]["sentiment"] == "bullish"  # 기존 필드 유지


def test_x_signals_to_dict_none_sentiment_fields() -> None:
    sig = XSignal(headline="h", summary="s", why_it_matters="w")
    dicts = x_signals_to_dict([sig])
    assert dicts[0]["sentiment_score"] is None
    assert dicts[0]["sentiment_confidence"] is None


def test_news_items_to_packet_includes_sentiment_fields() -> None:
    item = NewsItem(
        title="Test",
        url="https://example.com",
        source="Reuters",
        published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        sentiment_score=-0.42,
        sentiment_confidence=0.91,
    )
    packet = news_items_to_packet([item])
    assert packet[0]["sentiment_score"] == -0.42
    assert packet[0]["sentiment_confidence"] == 0.91


def test_news_items_to_packet_none_sentiment_fields() -> None:
    item = NewsItem(title="Test", url="https://example.com", source="Reuters", published_at=None)
    packet = news_items_to_packet([item])
    assert packet[0]["sentiment_score"] is None
    assert packet[0]["sentiment_confidence"] is None
