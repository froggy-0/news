from __future__ import annotations

import json
from types import SimpleNamespace

from morning_brief.config import load_settings
from morning_brief.public_news_analysis import enrich_public_news_packet


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=10,
        output_tokens=20,
        input_tokens_details=SimpleNamespace(cached_tokens=0),
        output_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )


def test_enrich_public_news_packet_merges_valid_results(monkeypatch):
    class FakeOpenAI:
        def __init__(self, *, api_key: str):
            self.responses = self

        def create(self, **kwargs):
            payload = json.loads(kwargs["input"])
            assert len(payload["items"]) == 1
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "items": [
                            {
                                "id": "news-1",
                                "summary_ko": "장기 금리가 올라 기술주 부담이 커졌습니다.",
                                "interpretation_ko": "고금리 부담이 성장주 선호를 약하게 만들 수 있습니다.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage=_usage(),
            )

    monkeypatch.setattr("morning_brief.public_news_analysis.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()

    enriched, audit = enrich_public_news_packet(
        items=[
            {
                "title": "Treasury yields rise as growth stocks wobble",
                "url": "https://www.reuters.com/world/us/treasury-yields-rise-growth-stocks-wobble",
                "source": "Reuters",
                "topic": "macro",
                "summary": "Yields moved higher after the latest Fed messaging.",
                "why_it_matters": "Growth stocks face a higher discount-rate burden.",
                "citations": [
                    "https://www.reuters.com/world/us/treasury-yields-rise-growth-stocks-wobble"
                ],
            }
        ],
        settings=settings,
    )

    assert enriched[0]["summary_ko"] == "장기 금리가 올라 기술주 부담이 커졌습니다."
    assert (
        enriched[0]["interpretation_ko"] == "고금리 부담이 성장주 선호를 약하게 만들 수 있습니다."
    )
    assert audit.status == "ok"
    assert audit.success_count == 1
    assert audit.failed_count == 0


def test_enrich_public_news_packet_ignores_placeholder_outputs(monkeypatch):
    class FakeOpenAI:
        def __init__(self, *, api_key: str):
            self.responses = self

        def create(self, **kwargs):
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "items": [
                            {
                                "id": "news-1",
                                "summary_ko": "해당 없음",
                                "interpretation_ko": "해당 없음",
                            },
                            {
                                "id": "news-2",
                                "summary_ko": "비트코인 ETF 자금 유입이 이어졌습니다.",
                                "interpretation_ko": "기관 수요 유지 기대가 단기 심리를 지지할 수 있습니다.",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage=_usage(),
            )

    monkeypatch.setattr("morning_brief.public_news_analysis.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()

    enriched, audit = enrich_public_news_packet(
        items=[
            {
                "title": "Macro placeholder test",
                "url": "https://www.reuters.com/world/us/macro-placeholder-test",
                "source": "Reuters",
                "topic": "macro",
                "summary": "Yields moved higher.",
                "why_it_matters": "Growth stocks face pressure.",
            },
            {
                "title": "Bitcoin ETF inflows stay positive",
                "url": "https://www.coindesk.com/markets/2026/03/22/bitcoin-etf-inflows-stay-positive/",
                "source": "CoinDesk",
                "topic": "bitcoin",
                "summary": "ETF inflows remained positive.",
                "why_it_matters": "Institutional demand looks stable.",
            },
        ],
        settings=settings,
    )

    assert "summary_ko" not in enriched[0]
    assert "interpretation_ko" not in enriched[0]
    assert enriched[1]["summary_ko"] == "비트코인 ETF 자금 유입이 이어졌습니다."
    assert audit.status == "partial"
    assert audit.success_count == 1
    assert audit.failed_count == 1


def test_enrich_public_news_packet_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("OPENAI_PUBLIC_NEWS_ANALYSIS_ENABLED", "false")
    settings = load_settings()

    enriched, audit = enrich_public_news_packet(
        items=[
            {
                "title": "Treasury yields rise",
                "url": "https://www.reuters.com/world/us/treasury-yields-rise",
                "source": "Reuters",
                "summary": "Yields moved higher.",
                "why_it_matters": "Growth stocks face pressure.",
            }
        ],
        settings=settings,
    )

    assert enriched[0].get("summary_ko") is None
    assert audit.status == "skipped"
    assert audit.skipped_count == 1


def test_enrich_public_news_packet_handles_invalid_json_response(monkeypatch):
    class FakeOpenAI:
        def __init__(self, *, api_key: str):
            self.responses = self

        def create(self, **kwargs):
            return SimpleNamespace(output_text='{"items":[{"id":"broken"', usage=_usage())

    monkeypatch.setattr("morning_brief.public_news_analysis.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()

    enriched, audit = enrich_public_news_packet(
        items=[
            {
                "title": "Treasury yields rise",
                "url": "https://www.reuters.com/world/us/treasury-yields-rise",
                "source": "Reuters",
                "summary": "Yields moved higher.",
                "why_it_matters": "Growth stocks face pressure.",
            }
        ],
        settings=settings,
    )

    assert "summary_ko" not in enriched[0]
    assert audit.status == "failed"
    assert audit.failed_count == 1
