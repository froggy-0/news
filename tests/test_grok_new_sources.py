"""Grok X Keyword Search + Web Search 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.sources.grok_web_search import (
    _article_to_news_item,
    _parse_datetime,
    _source_from_url,
    fetch_grok_web_news,
)
from morning_brief.data.sources.grok_x_keyword import (
    XSignal,
    _signal_to_news_item,
    _signal_to_x_signal,
    fetch_x_keyword_signals,
    x_signals_to_dict,
)


class TestXSignalToNewsItem:
    def test_basic_conversion(self):
        signal = XSignal(
            headline="Fed holds rates steady",
            summary="The Federal Reserve kept rates unchanged.",
            why_it_matters="Rate expectations shift.",
            sentiment="neutral",
            source_handle="NickTimiraos",
            posted_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
            topic="macro",
            citations=["https://x.com/NickTimiraos/status/123"],
        )
        item = _signal_to_news_item(signal)
        assert item.title == "Fed holds rates steady"
        assert item.provider == "grok_x_keyword"
        assert item.source == "@NickTimiraos"
        assert item.url == "https://x.com/NickTimiraos/status/123"

    def test_no_citations_uses_handle_url(self):
        signal = XSignal(
            headline="Test",
            summary="Test summary",
            why_it_matters="",
            source_handle="DeItaone",
            topic="macro",
        )
        item = _signal_to_news_item(signal)
        assert item.url == "https://x.com/DeItaone"


class TestSignalToXSignal:
    def test_valid_item(self):
        raw = {
            "headline": "PCE inflation rises",
            "summary": "Core PCE up 0.4% MoM",
            "why_it_matters": "Rate cut hopes crushed",
            "sentiment": "bearish",
            "source_handle": "@DeItaone",
            "posted_at": "2026-03-15T10:00:00Z",
        }
        signal = _signal_to_x_signal(raw, "macro")
        assert signal is not None
        assert signal.headline == "PCE inflation rises"
        assert signal.sentiment == "bearish"
        assert signal.source_handle == "DeItaone"  # @ stripped

    def test_missing_headline_returns_none(self):
        raw = {"summary": "test"}
        assert _signal_to_x_signal(raw, "macro") is None

    def test_missing_summary_returns_none(self):
        raw = {"headline": "test"}
        assert _signal_to_x_signal(raw, "macro") is None


class TestXSignalsToDict:
    def test_serialization(self):
        signals = [
            XSignal(
                headline="Test",
                summary="Summary",
                why_it_matters="Matters",
                sentiment="bullish",
                source_handle="test",
                posted_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
                topic="macro",
                citations=["https://x.com/test/1"],
            ),
        ]
        result = x_signals_to_dict(signals)
        assert len(result) == 1
        assert result[0]["headline"] == "Test"
        assert result[0]["sentiment"] == "bullish"
        assert result[0]["posted_at"] == "2026-03-15T00:00:00+00:00"


class TestFetchXKeywordSignals:
    def test_empty_api_key_returns_empty(self):
        signals, items, keywords = fetch_x_keyword_signals(api_key="", model="test")
        assert signals == []
        assert items == []
        assert keywords == {}
        assert items == []


class TestArticleToNewsItem:
    def test_valid_article(self):
        article = {
            "title": "Fed holds rates",
            "url": "https://www.reuters.com/fed-holds",
            "source": "Reuters",
            "published_at": "2026-03-15T10:00:00Z",
            "topic": "macro",
            "summary": "The Fed kept rates unchanged.",
        }
        item = _article_to_news_item(article)
        assert item is not None
        assert item.title == "Fed holds rates"
        assert item.provider == "grok_web_search"
        assert item.source == "Reuters"

    def test_missing_title_returns_none(self):
        assert _article_to_news_item({"url": "https://test.com"}) is None

    def test_missing_url_returns_none(self):
        assert _article_to_news_item({"title": "Test"}) is None

    def test_source_from_url_fallback(self):
        article = {"title": "Test", "url": "https://www.bloomberg.com/news/test"}
        item = _article_to_news_item(article)
        assert item is not None
        assert item.source == "Bloomberg"


class TestParseDateTime:
    def test_iso_format(self):
        result = _parse_datetime("2026-03-15T10:00:00Z")
        assert result is not None
        assert result.year == 2026

    def test_empty_returns_none(self):
        assert _parse_datetime("") is None
        assert _parse_datetime(None) is None


class TestSourceFromUrl:
    def test_known_domains(self):
        assert _source_from_url("https://www.reuters.com/article") == "Reuters"
        assert _source_from_url("https://www.bloomberg.com/news") == "Bloomberg"

    def test_unknown_domain(self):
        result = _source_from_url("https://example.com/page")
        assert result == "Example"


class TestFetchGrokWebNews:
    def test_empty_api_key_returns_empty(self):
        items = fetch_grok_web_news(api_key="", model="test")
        assert items == []
