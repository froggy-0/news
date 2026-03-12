from __future__ import annotations

from morning_brief.config import load_settings
from morning_brief.prompting import (
    build_prompt_cache_key,
    render_brief_prompts,
    render_web_search_prompts,
)


def test_render_brief_prompts_contains_contract_and_packet(monkeypatch):
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "market_brief_test")
    settings = load_settings()
    packet = {
        "macro": [{"label": "US2Y", "price": 4.12, "change_pct": 0.11}],
        "news": [{"title": "Example", "source": "Reuters"}],
        "data_quality": {"status": "ok", "warnings": []},
    }

    instructions, user_prompt = render_brief_prompts(packet=packet, settings=settings)

    assert "Morning Market Brief" in instructions
    assert "Prompt Version: market_brief_test" in instructions
    assert "<market_data_json>" in user_prompt
    assert '"macro":[{"label":"US2Y","price":4.12,"change_pct":0.11}]' in user_prompt


def test_prompt_cache_key_is_stable_and_sanitized(monkeypatch):
    monkeypatch.setenv("OPENAI_PROMPT_CACHE_KEY", "brief prod/cache")
    monkeypatch.setenv("PROMPT_TEMPLATE_VERSION", "v9")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    settings = load_settings()

    key_one = build_prompt_cache_key(settings=settings, instructions="same-static-instructions")
    key_two = build_prompt_cache_key(settings=settings, instructions="same-static-instructions")
    key_three = build_prompt_cache_key(settings=settings, instructions="changed-static-instructions")

    assert key_one == key_two
    assert key_one != key_three
    assert " " not in key_one
    assert "/" not in key_one


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
