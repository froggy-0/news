from __future__ import annotations

from morning_brief.emailer import (
    _extract_brief_structure,
    _split_section_groups,
    _split_recipients,
    _split_reference_block,
    build_briefing_message,
    render_briefing_email_html,
)


SAMPLE_BRIEF = """Morning Market Brief (2026-03-12)
[데이터 품질 알림] 뉴스 수가 부족합니다.

1. 거시 환경
수치 체크
- 미국 10년물 금리는 4.20%였어요.

해석
금리 흐름은 기술주 밸류에이션에 영향을 주고 있어요. 달러 방향도 함께 봐야 해요.

2. 미국 증시 흐름
수치 체크
- 나스닥이 1.2% 올랐어요.

해석
반도체가 상대적으로 견조했어요. 시장 폭이 넓어지는지는 더 봐야 해요.

5. 중요한 뉴스
핵심 내용
- 엔비디아가 신규 AI 투자 계획을 공개했습니다.
- 비트코인 ETF 자금 유입이 재개됐습니다.

해석
AI 투자 기대와 ETF 수급 개선이 함께 읽혔어요.
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
        subject="좋은 아침이에요 | 미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=SAMPLE_BRIEF,
    )

    assert "좋은 아침 시장 브리핑" in html
    assert "안녕하세요." in html
    assert "오늘 아침에 꼭 봐야 할 시장 흐름만 편하게 읽으실 수 있게 정리했어요." in html
    assert "미국 기술주와 비트코인" in html
    assert "편하게 읽으실 수 있게 담았어요." in html
    assert "-webkit-text-fill-color:#0f172a" in html
    assert "Pretendard" in html
    assert "<li style=" in html
    assert "list-style:none" in html
    assert "↑" in html
    assert "#dc2626" in html
    assert "#fef2f2" in html
    assert "alpha@example.com" not in html
    assert "[데이터 품질 알림] 뉴스 수가 부족합니다." in html
    assert "수치 체크" in html
    assert "해석" in html


def test_split_section_groups_separates_summary_and_insight():
    label, summary, insight = _split_section_groups(
        "수치 체크\n- 나스닥이 1.2% 올랐어요.\n\n해석\n강세 흐름이 이어졌어요. 다만 시장 폭은 더 봐야 해요."
    )

    assert label == "수치 체크"
    assert "- 나스닥이 1.2% 올랐어요." in summary
    assert "강세 흐름이 이어졌어요." in insight
    assert "다만 시장 폭은 더 봐야 해요." in insight


def test_render_briefing_email_html_marks_down_moves_in_blue():
    html = render_briefing_email_html(
        subject="좋은 아침이에요 | 미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

1. 미국 증시 흐름
수치 체크
- 엔비디아가 2.4% 내렸어요.
""",
    )

    assert "↓" in html
    assert "#2563eb" in html
    assert "#eff6ff" in html
    assert '<span style="color:#2563eb;font-weight:700;">2.4%</span>' in html
    assert "엔비디아가 2.4% 내렸어요." in html


def test_build_briefing_message_uses_bcc_for_multiple_recipients():
    msg = build_briefing_message(
        subject="좋은 아침이에요 | 미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=SAMPLE_BRIEF,
        sender="sender@example.com",
        recipients=["a@example.com", "b@example.com"],
    )

    assert msg["to"] == "sender@example.com"
    assert msg["bcc"] == "a@example.com, b@example.com"
    assert msg.get_payload()[0].get_content_type() == "text/plain"
    assert msg.get_payload()[1].get_content_type() == "text/html"


def test_render_briefing_email_html_renders_reference_links():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Reuters — https://www.reuters.com/world/us/example"

    html = render_briefing_email_html(
        subject="좋은 아침이에요 | 미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "참고 출처" in html
    assert 'href="https://www.reuters.com/world/us/example"' in html


def test_split_reference_block_separates_reference_lines():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Reuters — https://www.reuters.com/world/us/example"

    main_body, references = _split_reference_block(body)

    assert "참고 출처" not in main_body
    assert references == ["Reuters — https://www.reuters.com/world/us/example"]
