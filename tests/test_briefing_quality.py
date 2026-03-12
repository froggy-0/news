from __future__ import annotations

from morning_brief.briefing import (
    _fallback_brief,
    _improve_readability_spacing,
    _inject_quality_notice,
    generate_briefing,
)
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


def test_improve_readability_spacing_breaks_sentences():
    text = "Morning Market Brief (2026-03-12)\n\n1. 거시 환경\n금리는 올랐어요. 달러도 강했어요."

    updated = _improve_readability_spacing(text)

    assert "금리는 올랐어요.\n\n달러도 강했어요." in updated


def test_fallback_brief_mentions_official_btc_etf_flow_when_available():
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 80_000.0, "change_pct": 1.5},
            "etf_points": [],
            "etf_total_volume": 123_456,
            "official_etf_supported_tickers": ["IBIT", "BITB", "GBTC"],
            "official_etf_compared_tickers": ["IBIT", "BITB", "GBTC"],
            "official_etf_total_btc": 981_234.56,
            "official_etf_daily_flow_btc": 1_234.56,
            "official_etf_daily_flow_usd": 98_764_800.0,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "공식 발행사 기준으로 집계한 IBIT, BITB, GBTC 합산 보유량은 981,234.56 BTC였어요." in briefing
    assert "직전 스냅샷과 비교한 공식 ETF 흐름은 1,234.56 BTC 순유입" in briefing
