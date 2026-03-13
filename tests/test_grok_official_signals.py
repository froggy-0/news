from __future__ import annotations

import json
from datetime import datetime, timezone

from morning_brief.data.sources import grok_official_signals as gxs


class _Response:
    def __init__(self, *, content: str, citations: list[object] | None = None):
        self.content = content
        self.citations = citations or []


class _Chat:
    def __init__(self, response: _Response, calls: list[dict], prompts: list[object]):
        self._response = response
        self._calls = calls
        self._prompts = prompts

    def append(self, message):
        self._prompts.append(message)
        return self

    def sample(self):
        return self._response


class _ChatResource:
    def __init__(self, responses: list[_Response], calls: list[dict], prompts: list[object]):
        self._responses = responses
        self._calls = calls
        self._prompts = prompts

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return _Chat(self._responses.pop(0), self._calls, self._prompts)


class _Client:
    def __init__(self, responses: list[_Response], calls: list[dict], prompts: list[object]):
        self.chat = _ChatResource(responses, calls, prompts)


VERIFIED_GROUPS = {
    "ai_bigtech_primary": [
        {
            "entity_id": "amd",
            "entity_name": "AMD",
            "ticker": "AMD",
            "newsroom_or_ir_url": "https://www.amd.com/en/newsroom.html",
            "x_handle": "AMD",
            "x_search_priority": 1,
        }
    ],
    "btc_etf_primary": [
        {
            "entity_id": "fidelity",
            "entity_name": "Fidelity",
            "ticker": "FBTC",
            "newsroom_or_ir_url": "https://www.fidelity.com/etfs/fbtc",
            "x_handle": "Fidelity",
            "x_search_priority": 1,
        }
    ],
}



def test_fetch_official_x_signals_collects_verified_groups(monkeypatch):
    calls: list[dict] = []
    prompts: list[object] = []
    responses = [
        _Response(
            content=json.dumps(
                {
                    "items": [
                        {
                            "entity_id": "amd",
                            "headline": "AMD가 새 AI 서버 투자 계획을 공개했어요",
                            "summary": "공식 계정이 데이터센터 투자 계획을 설명했어요.",
                            "why_it_matters": "AI 투자 지출 기대를 다시 키울 수 있어요.",
                            "posted_at": "2026-03-13T01:00:00Z",
                            "source_handle": "AMD",
                            "citations": ["https://x.com/AMD/status/1"],
                        }
                    ]
                }
            )
        ),
        _Response(
            content=json.dumps(
                {
                    "items": [
                        {
                            "entity_id": "fidelity",
                            "headline": "Fidelity가 ETF 운용 관련 공지를 올렸어요",
                            "summary": "공식 계정이 ETF 운용 업데이트를 안내했어요.",
                            "why_it_matters": "ETF 수급 해석에 직접 참고할 수 있어요.",
                            "posted_at": "2026-03-13T02:30:00Z",
                            "source_handle": "Fidelity",
                            "citations": ["https://x.com/Fidelity/status/2"],
                        }
                    ]
                }
            )
        ),
    ]

    monkeypatch.setattr(gxs, "grouped_verified_x_entities", lambda: VERIFIED_GROUPS)
    monkeypatch.setattr(gxs, "x_search", lambda **kwargs: {"name": "x_search", "kwargs": kwargs})
    monkeypatch.setattr(gxs, "_build_client", lambda api_key: _Client(responses, calls, prompts))

    items = gxs.fetch_official_x_signals(
        api_key="grok-test-key",
        model="grok-test-model",
        lookback_hours=48,
        max_items=4,
    )

    assert len(calls) == 2
    assert calls[0]["model"] == "grok-test-model"
    assert calls[0]["tools"][0]["kwargs"]["allowed_x_handles"] == ["AMD"]
    assert calls[1]["tools"][0]["kwargs"]["allowed_x_handles"] == ["Fidelity"]
    assert calls[0]["tool_choice"] == "required"
    assert prompts
    assert [item.provider for item in items] == ["grok_official_x", "grok_official_x"]
    assert items[0].title == "Fidelity가 ETF 운용 관련 공지를 올렸어요"
    assert items[0].topic == "bitcoin"
    assert items[1].topic == "ai_bigtech"
    assert items[1].citations == ["https://x.com/AMD/status/1"]
    assert items[1].published_at == datetime(2026, 3, 13, 1, 0, tzinfo=timezone.utc)



def test_fetch_official_x_signals_uses_response_citations_fallback(monkeypatch):
    calls: list[dict] = []
    prompts: list[object] = []
    responses = [
        _Response(
            content=json.dumps(
                {
                    "items": [
                        {
                            "entity_id": "amd",
                            "headline": "AMD가 공식 일정을 다시 안내했어요",
                            "summary": "공식 계정이 이벤트 일정을 다시 정리했어요.",
                            "why_it_matters": "이벤트 일정 확인에 직접 쓸 수 있어요.",
                            "posted_at": "2026-03-13T01:00:00Z",
                            "source_handle": "AMD",
                            "citations": [],
                        }
                    ]
                }
            ),
            citations=[{"url": "https://x.com/AMD/status/3"}],
        )
    ]

    monkeypatch.setattr(gxs, "grouped_verified_x_entities", lambda: {"ai_bigtech_primary": VERIFIED_GROUPS["ai_bigtech_primary"]})
    monkeypatch.setattr(gxs, "x_search", lambda **kwargs: {"name": "x_search", "kwargs": kwargs})
    monkeypatch.setattr(gxs, "_build_client", lambda api_key: _Client(responses, calls, prompts))

    items = gxs.fetch_official_x_signals(
        api_key="grok-test-key",
        model="grok-test-model",
        lookback_hours=24,
        max_items=2,
    )

    assert items[0].citations == ["https://x.com/AMD/status/3"]
    assert items[0].url == "https://x.com/AMD/status/3"



def test_fetch_official_x_signals_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(gxs, "grouped_verified_x_entities", lambda: VERIFIED_GROUPS)

    items = gxs.fetch_official_x_signals(
        api_key="",
        model="grok-test-model",
        lookback_hours=24,
        max_items=2,
    )

    assert items == []
