"""Perplexity Sonar 클라이언트 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from morning_brief.data.sources.perplexity_sonar import (
    TopicSummary,
    _citations_to_news_items,
    _parse_sonar_content,
    collect_sonar_news_items,
    fetch_sonar_summaries,
    topic_summaries_to_dict,
)


class TestParseSonarContent:
    def test_valid_json(self):
        raw = '{"topic":"macro","summary_text":"Fed held rates.","key_data_points":[{"label":"Fed Rate","value":"5.25%","change":"+0bp","source":"Reuters"}],"market_implication":"Rates steady.","notable_stocks":[]}'
        result = _parse_sonar_content(raw, "macro")
        assert result["topic"] == "macro"
        assert result["summary_text"] == "Fed held rates."
        assert len(result["key_data_points"]) == 1
        assert result["market_implication"] == "Rates steady."

    def test_json_with_code_fence(self):
        raw = '```json\n{"topic":"macro","summary_text":"test","key_data_points":[],"market_implication":"","notable_stocks":[]}\n```'
        result = _parse_sonar_content(raw, "macro")
        assert result["topic"] == "macro"
        assert result["summary_text"] == "test"

    def test_invalid_json_returns_text_as_summary(self):
        raw = "This is not JSON but a plain text summary."
        result = _parse_sonar_content(raw, "us_equity")
        assert result["topic"] == "us_equity"
        assert "not JSON" in result["summary_text"]
        assert result["key_data_points"] == []

    def test_empty_string(self):
        result = _parse_sonar_content("", "bitcoin")
        assert result["topic"] == "bitcoin"

    def test_missing_fields_get_defaults(self):
        raw = '{"topic":"us_equity"}'
        result = _parse_sonar_content(raw, "us_equity")
        assert result["summary_text"] == ""
        assert result["key_data_points"] == []
        assert result["market_implication"] == ""
        assert result["notable_stocks"] == []


class TestCitationsToNewsItems:
    def test_valid_urls(self):
        citations = [
            "https://www.reuters.com/markets/us-fed-holds-rates",
            "https://www.bloomberg.com/news/nvidia-earnings",
        ]
        items = _citations_to_news_items(citations, "macro")
        assert len(items) == 2
        assert items[0].provider == "perplexity_sonar"
        assert items[0].topic == "macro"
        assert items[0].url == citations[0]

    def test_non_http_urls_skipped(self):
        citations = ["not-a-url", "https://valid.com/article"]
        items = _citations_to_news_items(citations, "bitcoin")
        assert len(items) == 1

    def test_empty_citations(self):
        items = _citations_to_news_items([], "macro")
        assert items == []

    def test_file_like_citation_urls_are_skipped(self):
        citations = [
            "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a1.htm",
            "https://www.federalreserve.gov/monetarypolicy/files/monetary20260318a1.pdf",
            "https://www.reuters.com/markets/us-fed-holds-rates",
        ]
        items = _citations_to_news_items(citations, "macro")
        assert len(items) == 1
        assert items[0].url == "https://www.reuters.com/markets/us-fed-holds-rates"
        assert items[0].title == "us fed holds rates"


class TestCollectSonarNewsItems:
    def test_deduplicates_urls(self):
        url = "https://reuters.com/article"
        summaries = {
            "macro": TopicSummary(
                topic="macro",
                news_items=[
                    MagicMock(url=url),
                    MagicMock(url=url),
                ],
            ),
        }
        items = collect_sonar_news_items(summaries)
        assert len(items) == 1

    def test_multiple_topics(self):
        summaries = {
            "macro": TopicSummary(
                topic="macro",
                news_items=[MagicMock(url="https://a.com/1")],
            ),
            "bitcoin": TopicSummary(
                topic="bitcoin",
                news_items=[MagicMock(url="https://b.com/2")],
            ),
        }
        items = collect_sonar_news_items(summaries)
        assert len(items) == 2


class TestTopicSummariesToDict:
    def test_serialization(self):
        summaries = {
            "macro": TopicSummary(
                topic="macro",
                summary_text="Fed held rates.",
                key_data_points=[
                    {"label": "Rate", "value": "5.25%", "change": "0", "source": "Fed"}
                ],
                market_implication="Steady.",
                citations=["https://reuters.com/fed"],
            ),
        }
        result = topic_summaries_to_dict(summaries)
        assert "macro" in result
        assert result["macro"]["summary_text"] == "Fed held rates."
        assert len(result["macro"]["key_data_points"]) == 1
        assert result["macro"]["citations"] == ["https://reuters.com/fed"]


class TestFetchSonarSummaries:
    def test_empty_api_key_returns_empty(self):
        result = fetch_sonar_summaries(api_key="", model="sonar")
        assert result == {}

    def test_whitespace_api_key_returns_empty(self):
        result = fetch_sonar_summaries(api_key="   ", model="sonar")
        assert result == {}
