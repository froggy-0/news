from __future__ import annotations

from morning_brief.config import load_settings
from morning_brief.prompting import (
    build_prompt_cache_key,
    render_brief_prompts,
    render_brief_rewrite_prompts,
    render_brief_validator_prompts,
    render_web_search_prompts,
)


def test_render_brief_prompts_contains_contract_and_packet(monkeypatch):
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "market_brief_test")
    settings = load_settings()
    packet = {
        "macro": [{"label": "US2Y", "price": 4.12, "change_pct": None, "change_bps": 11.0}],
        "news": [
            {
                "title": "Example",
                "source": "Reuters",
                "topic": "macro",
                "summary": "Fed 관련 기사예요.",
                "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
                "citations": ["https://www.reuters.com/example"],
            },
            {
                "title": "Official update",
                "source": "@AMD",
                "topic": "ai_bigtech",
                "provider": "grok_official_x",
                "official_source": True,
                "summary": "AMD 공식 계정이 투자 계획을 다시 설명했어요.",
                "why_it_matters": "공식 채널 확인이라 해석의 우선 근거가 돼요.",
                "citations": ["https://x.com/AMD/status/1"],
            },
        ],
        "data_quality": {"status": "ok", "warnings": []},
    }

    instructions, user_prompt = render_brief_prompts(packet=packet, settings=settings)

    assert "Morning Market Brief" in instructions
    # V2 Section 구조 검증
    assert "오늘의 핵심" in instructions
    assert "핵심 뉴스 5선" in instructions
    assert "섹터/자산 영향 매핑" in instructions
    assert "이벤트 캘린더" in instructions
    assert "수혜" in instructions
    assert "압력" in instructions
    assert "중립" in instructions
    assert "원/달러" in instructions
    assert "나스닥 선물" in instructions
    assert "상관관계" in instructions
    assert "장단기 스프레드는 별도 계산 수치라 이번 브리핑에서는 적지 않아요." in user_prompt
    assert (
        "BTC 현물 절대값은 `market_data_json.bitcoin.spot.price` 숫자 그대로만 사용해요."
        in user_prompt
    )
    assert "Prompt Version: market_brief_test" in instructions
    assert "<market_data_json>" in user_prompt
    assert "<news_focus_json>" in user_prompt
    assert (
        '"macro":[{"label":"US2Y","price":4.12,"change_pct":null,"change_bps":11.0}]' in user_prompt
    )
    assert '"topic":"macro"' in user_prompt
    assert '"why_it_matters":"금리 흐름을 읽는 데 도움이 되는 기사예요."' in user_prompt
    assert '"official_signals"' in user_prompt


def test_prompt_cache_key_is_stable_and_sanitized(monkeypatch):
    monkeypatch.setenv("OPENAI_PROMPT_CACHE_KEY", "brief prod/cache")
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "v9")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    settings = load_settings()

    key_one = build_prompt_cache_key(settings=settings, instructions="same-static-instructions")
    key_two = build_prompt_cache_key(settings=settings, instructions="same-static-instructions")
    key_three = build_prompt_cache_key(
        settings=settings, instructions="changed-static-instructions"
    )

    assert key_one == key_two
    assert key_one != key_three
    assert " " not in key_one
    assert "/" not in key_one
    assert len(key_one) <= 64


def test_prompt_cache_key_changes_with_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_PROMPT_CACHE_KEY", "brief prod/cache")
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "v9")
    settings = load_settings()

    key_default = build_prompt_cache_key(settings=settings, instructions="same-static-instructions")
    key_override = build_prompt_cache_key(
        settings=settings,
        instructions="same-static-instructions",
        model_name="gpt-5",
    )

    assert key_default != key_override
    assert len(key_default) <= 64
    assert len(key_override) <= 64


def test_prompt_cache_key_respects_openai_length_limit_for_default_snapshot(monkeypatch):
    monkeypatch.delenv("OPENAI_PROMPT_CACHE_KEY", raising=False)
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "market_brief_v4")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini-2025-08-07")
    settings = load_settings()

    key = build_prompt_cache_key(
        settings=settings,
        instructions="same-static-instructions",
    )

    assert len(key) <= 64
    assert key.count(":") == 3


def test_render_web_search_prompts_contains_search_context(monkeypatch):
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "market_brief_test")
    settings = load_settings()

    instructions, user_prompt = render_web_search_prompts(
        search_context_json='{"quality":{"status":"degraded"},"max_results":3}',
        settings=settings,
    )

    assert "JSON 객체" in instructions
    assert "<search_context_json>" in user_prompt
    assert '"max_results":3' in user_prompt


def test_render_brief_validator_prompts_contains_draft_and_packet(monkeypatch):
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "market_brief_test")
    settings = load_settings()

    instructions, user_prompt = render_brief_validator_prompts(
        packet_json='{"macro":[{"label":"US10Y"}]}',
        draft_text="Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n...",
        settings=settings,
    )

    assert "품질 검수 에디터" in instructions
    assert "4-2" in instructions
    assert "한국어 헤드라인" in instructions
    assert "None" in instructions
    assert "수혜" in instructions
    assert "Prompt Version: market_brief_test" in instructions
    assert "<brief_text>" in user_prompt
    assert '"macro":[{"label":"US10Y"}]' in user_prompt


def test_render_brief_rewrite_prompts_contains_review_feedback(monkeypatch):
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "market_brief_test")
    settings = load_settings()

    instructions, user_prompt = render_brief_rewrite_prompts(
        packet_json='{"macro":[]}',
        draft_text="Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n...",
        review_json='{"pass":false,"rewrite_guidance":["쉬운 말로 바꾸기"]}',
        settings=settings,
    )

    assert "교정 에디터" in instructions
    assert "섹션 번호와 제목 구조" in instructions
    assert "자연스러운 한국어" in instructions
    assert "LAYER" in instructions  # "LAYER라는 단어를 사용하지 않는다" 규칙 포함
    assert "<review_json>" in user_prompt
    assert '"rewrite_guidance":["쉬운 말로 바꾸기"]' in user_prompt
