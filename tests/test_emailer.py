from __future__ import annotations

from morning_brief.emailer import (
    _extract_brief_structure,
    _split_recipients,
    build_briefing_message,
    render_briefing_email_html,
)


SAMPLE_BRIEF = """Morning Market Brief (2026-03-12)
[데이터 품질 알림] 뉴스 수가 부족합니다.

1. 거시 환경
금리와 달러는 기술주 밸류에이션에 직접적인 영향을 줍니다.

2. 미국 증시 흐름
나스닥이 강세를 보였고 반도체가 상대적으로 견조했습니다.

5. 중요한 뉴스
- 엔비디아가 신규 AI 투자 계획을 공개했습니다.
- 비트코인 ETF 자금 유입이 재개됐습니다.
"""


def test_split_recipients_deduplicates_and_trims():
    recipients = _split_recipients(" alpha@example.com, beta@example.com ,alpha@example.com ")

    assert recipients == ["alpha@example.com", "beta@example.com"]


def test_extract_brief_structure_parses_title_notice_and_sections():
    title, notice, sections = _extract_brief_structure(SAMPLE_BRIEF)

    assert title == "Morning Market Brief (2026-03-12)"
    assert notice == "[데이터 품질 알림] 뉴스 수가 부족합니다."
    assert sections[0][0] == "거시 환경"
    assert sections[1][0] == "미국 증시 흐름"
    assert sections[2][0] == "중요한 뉴스"


def test_render_briefing_email_html_contains_modern_layout_and_list_items():
    html = render_briefing_email_html(
        subject="Morning Market Brief | 2026-03-12",
        body=SAMPLE_BRIEF,
    )

    assert "US Tech + BTC Morning Brief" in html
    assert "3-5분 읽기" in html
    assert "<li style=" in html
    assert "alpha@example.com" not in html
    assert "[데이터 품질 알림] 뉴스 수가 부족합니다." in html


def test_build_briefing_message_uses_bcc_for_multiple_recipients():
    msg = build_briefing_message(
        subject="Morning Market Brief | 2026-03-12",
        body=SAMPLE_BRIEF,
        sender="sender@example.com",
        recipients=["a@example.com", "b@example.com"],
    )

    assert msg["to"] == "Undisclosed recipients:;"
    assert msg["bcc"] == "a@example.com, b@example.com"
    assert msg.get_payload()[0].get_content_type() == "text/plain"
    assert msg.get_payload()[1].get_content_type() == "text/html"
