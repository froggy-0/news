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
핵심 판단
- 금리와 달러 흐름이 기술주 심리에 부담으로 작용했습니다.

주요 지표
- 미국 10년물 금리는 4.20%였습니다.

배경과 해석
금리 흐름은 기술주 주가 부담에 영향을 주고 있습니다. 달러 방향도 함께 볼 필요가 있습니다.

주목할 변수
- 장기금리가 더 오르는지 함께 볼 필요가 있습니다.

2. 미국 증시 흐름
핵심 판단
- 반도체가 지수를 조금 더 잘 버텼습니다.

주요 지표
- 나스닥이 1.2% 상승했습니다.

배경과 해석
반도체가 상대적으로 견조했습니다. 시장 폭이 넓어지는지는 더 볼 필요가 있습니다.

주목할 변수
- 대형 기술주로만 쏠리는지 확인이 필요합니다.

5. 중요한 뉴스
핵심 판단
- AI 투자 기대와 ETF 자금 흐름이 함께 읽혔습니다.

핵심 이슈
- 엔비디아가 신규 AI 투자 계획을 공개했습니다.
- 비트코인 ETF 자금 유입이 재개됐습니다.

배경과 해석
AI 투자 기대와 ETF 수급 개선이 함께 읽혔습니다.

주목할 변수
- 관련 기대가 오늘도 이어지는지 살펴볼 필요가 있습니다.
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
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=SAMPLE_BRIEF,
    )

    assert "미국 기술주 · 비트코인 시장 브리핑" in html
    assert "핵심 요약" in html
    assert "주요 지표" in html
    assert "2026.03.12" in html
    assert "-webkit-text-fill-color:#0f172a" in html
    assert "Pretendard" in html
    assert "한 번에 핵심만 읽을 수 있게 정리한 아침 시장 메일이에요." not in html
    assert "<li style=" in html
    assert "list-style:none" in html
    assert "↑" not in html
    assert "↓" not in html
    assert "#dc2626" in html
    assert "alpha@example.com" not in html
    assert "[데이터 품질 알림] 뉴스 수가 부족합니다." in html
    assert "핵심 판단" in html
    assert "배경과 해석" in html
    assert "주목할 변수" in html


def test_split_section_groups_separates_summary_and_insight():
    groups = _split_section_groups(
        "한줄 결론\n- 반도체가 지수를 조금 더 잘 버텼습니다.\n\n핵심 수치\n- 나스닥이 1.2% 상승했습니다.\n\n쉽게 보면\n강세 흐름이 이어졌습니다. 다만 시장 폭은 더 볼 필요가 있습니다.\n\n오늘 체크할 포인트\n- 대형 기술주로만 쏠리는지 볼 필요가 있습니다."
    )

    assert groups["conclusion"][0] == "핵심 판단"
    assert "- 반도체가 지수를 조금 더 잘 버텼습니다." in groups["conclusion"][1]
    assert "- 나스닥이 1.2% 상승했습니다." in groups["metrics"][1]
    assert "강세 흐름이 이어졌습니다." in groups["insight"][1]
    assert "대형 기술주로만 쏠리는지 볼 필요가 있습니다." in groups["watch"][1]


def test_render_briefing_email_html_marks_down_moves_in_blue():
    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

1. 미국 증시 흐름
주요 지표
- 엔비디아가 2.4% 하락했습니다.
""",
    )

    assert "#2563eb" in html
    assert "↑" not in html
    assert "↓" not in html
    assert '<span style="color:#2563eb;font-weight:700;">2.4%</span>' in html
    assert "엔비디아가 2.4% 하락했습니다." in html


def test_render_briefing_email_html_colors_each_signed_percent_individually():
    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

1. 미국 증시 흐름
주요 지표
- 주요 지수는 S&P500 610.25 (+1.20%) / NASDAQ 18250.11 (-0.85%) / SOXX 245.10 (+0.10%) 흐름으로 마감했습니다.
""",
    )

    assert '<span style="color:#dc2626;font-weight:700;">+1.20%</span>' in html
    assert '<span style="color:#2563eb;font-weight:700;">-0.85%</span>' in html
    assert '<span style="color:#dc2626;font-weight:700;">+0.10%</span>' in html


def test_render_briefing_email_html_prefers_negative_numeric_direction_over_positive_words():
    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

1. 시장 해석
주목할 변수
- 나스닥은 -1.20%였지만 단기 반등 기대는 아직 남아 있습니다.
""",
    )

    assert '<span style="color:#2563eb;font-weight:700;">-1.20%</span>' in html


def test_build_briefing_message_uses_bcc_for_multiple_recipients():
    msg = build_briefing_message(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
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
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "주요 참고 출처" in html
    assert 'href="https://www.reuters.com/world/us/example"' in html


def test_render_briefing_email_html_omits_unsafe_reference_links():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Bad Link — javascript:alert(1)"

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "Bad Link" in html
    assert "javascript:alert(1)" not in html
    assert 'href="javascript:alert(1)"' not in html


def test_split_reference_block_separates_reference_lines():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Reuters — https://www.reuters.com/world/us/example"

    main_body, references = _split_reference_block(body)

    assert "참고 출처" not in main_body
    assert references == ["Reuters — https://www.reuters.com/world/us/example"]
