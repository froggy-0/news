from __future__ import annotations

from morning_brief.briefing import _fallback_brief, _inject_quality_notice, generate_briefing
from morning_brief.config import load_settings



def test_inject_quality_notice_under_title():
    packet = {
        "data_quality": {
            "status": "critical",
            "warnings": ["가격 데이터 부족", "뉴스 부족"],
        }
    }
    text = "Morning Market Brief (2026-03-12)\n\n1. 거시 환경\n본문"

    updated = _inject_quality_notice(text, packet)

    assert "[데이터 품질 알림]" in updated
    lines = updated.splitlines()
    assert lines[0].startswith("Morning Market Brief")
    assert lines[1].startswith("[데이터 품질 알림]")


def test_generate_briefing_falls_back_when_prompt_rendering_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "etf_total_volume": 0},
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    monkeypatch.setattr(
        "morning_brief.briefing.render_brief_prompts",
        lambda **_: (_ for _ in ()).throw(RuntimeError("template missing")),
    )

    briefing = generate_briefing(packet=packet, settings=settings)

    assert briefing == _fallback_brief(packet=packet, timezone=settings.timezone)
