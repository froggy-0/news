from __future__ import annotations

from morning_brief.briefing import _inject_quality_notice



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
