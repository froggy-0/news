from __future__ import annotations

from morning_brief.emailer import (
    _build_email_context,
    _extract_brief_structure,
    _split_recipients,
    _split_reference_block,
    _split_section_groups,
    build_briefing_message,
    render_briefing_email_html,
    render_briefing_email_text,
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


def test_render_briefing_email_html_contains_layered_mobile_layout():
    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=SAMPLE_BRIEF,
    )

    assert "Morning Market Brief" in html
    assert "Layer 1 · 오늘 한줄 판단" in html
    assert "Layer 2 · 주요 뉴스" in html
    assert "Layer 3 · 종목 브리핑" in html
    assert "2026.03.12" in html
    assert "prefers-color-scheme: dark" in html
    assert "-apple-system" in html
    assert "display:none;max-height:0" in html
    assert "대표 출처 열기" not in html
    assert "GitHub에서 보기" in html
    assert "구독 해지" in html
    assert "GitHub" in html
    assert "[데이터 품질 알림] 뉴스 수가 부족합니다." in html
    assert "거시 지표" in html
    assert html.count("2026.03.12") == 1


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

    assert "#dc2626" in html
    assert "↑" not in html
    assert "↓" not in html
    assert ">2.4%<" in html
    assert "엔비디아가 2.4% 하락했습니다." in html


def test_render_briefing_email_html_colors_each_signed_percent_individually():
    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

3. LAYER 3 | 종목 브리핑
주요 지표
- S&P500 | +1.20% | 지수 흐름입니다. | [출처: Stooq]
- NASDAQ | -0.85% | 기술주 흐름입니다. | [출처: Stooq]
- SOXX | +0.10% | 반도체 흐름입니다. | [출처: Stooq]
""",
    )

    assert "#16a34a" in html
    assert "#dc2626" in html
    assert "+1.20%" in html
    assert "-0.85%" in html
    assert "+0.10%" in html


def test_render_briefing_email_html_prefers_negative_numeric_direction_over_positive_words():
    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

1. 시장 해석
주목할 변수
- 나스닥은 -1.20%였지만 단기 반등 기대는 아직 남아 있습니다.
""",
    )

    assert "#dc2626" in html
    assert "-1.20%" in html


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
    assert "구독 해지" in msg.get_payload()[0].get_payload(decode=True).decode("utf-8")


def test_render_briefing_email_html_renders_reference_links():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Reuters — https://www.reuters.com/world/us/example"

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "출처" in html
    assert "시장 데이터" in html
    assert 'href="https://www.reuters.com/world/us/example"' in html


def test_render_briefing_email_html_moves_news_url_to_source_section():
    body = """Morning Market Brief (2026-03-12)

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 엔비디아가 새 AI 클러스터를 공개했습니다 | 데이터센터 투자 기대를 자극했습니다.

참고 출처
- 엔비디아가 새 AI 클러스터를 공개했습니다 — https://www.reuters.com/world/us/example
"""

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "엔비디아가 새 AI 클러스터를 공개했습니다" in html
    assert "출처: reuters.com" not in html
    assert '<a href="https://www.reuters.com/world/us/example"' in html
    assert ">https://www.reuters.com/world/us/example<" in html


def test_render_briefing_email_html_leaves_headline_plain_text_when_url_missing():
    body = """Morning Market Brief (2026-03-12)

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 엔비디아가 새 AI 클러스터를 공개했습니다 | 데이터센터 투자 기대를 다시 자극했습니다.
"""

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "엔비디아가 새 AI 클러스터를 공개했습니다" in html
    assert 'href="https://"' not in html


def test_render_briefing_email_html_keeps_x_signal_url_only_in_source_section():
    body = """Morning Market Brief (2026-03-12)

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 블랙록이 BTC ETF 유입 현황을 업데이트했습니다 | 공식 X 업데이트입니다.

참고 출처
- 블랙록이 BTC ETF 유입 현황을 업데이트했습니다 — https://x.com/BlackRock/status/1234567890
"""

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "블랙록이 BTC ETF 유입 현황을 업데이트했습니다" in html
    assert "출처: x.com/BlackRock" not in html
    assert 'href="https://x.com/BlackRock/status/1234567890"' in html


def test_render_briefing_email_html_omits_unsafe_reference_links():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Bad Link — javascript:alert(1)"

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "Bad Link" in html
    assert "javascript:alert(1)" not in html
    assert 'href="javascript:alert(1)"' not in html


def test_render_briefing_email_html_renders_data_footer_notes():
    body = SAMPLE_BRIEF + "\n\n데이터 처리 메모\n- 달러 인덱스는 허용 범위를 벗어나 생략했어요."

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "데이터 처리 메모" in html
    assert "달러 인덱스는 허용 범위를 벗어나 생략했어요." in html


def test_render_briefing_email_text_builds_plain_text_fallback():
    text = render_briefing_email_text(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=SAMPLE_BRIEF + "\n\n참고 출처\n- Reuters — https://www.reuters.com/world/us/example",
        sender="sender@example.com",
    )

    assert "[LAYER 2 | 주요 뉴스]" in text
    assert "[LAYER 3 | 종목 브리핑]" in text
    assert "구독 해지: mailto:sender@example.com" in text
    assert "GitHub: https://github.com/froggy-0/news" in text


def test_render_briefing_email_text_renders_full_news_url_when_present():
    text = render_briefing_email_text(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body="""Morning Market Brief (2026-03-12)

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 엔비디아가 새 AI 클러스터를 공개했습니다 | 데이터센터 투자 기대를 다시 자극했습니다.

참고 출처
- 엔비디아가 새 AI 클러스터를 공개했습니다 — https://www.reuters.com/world/us/example
""",
    )

    assert "출처 URL:" not in text
    assert "[출처]" in text
    assert "https://www.reuters.com/world/us/example" in text


def test_render_briefing_email_keeps_layer_sections_when_item_parsing_fails():
    body = """Morning Market Brief (2026-03-12)

2. LAYER 2 | 주요 뉴스
핵심 이슈
시장 영향이 큰 뉴스 후보를 우선 정리했습니다.

배경과 해석
기사 형식이 완전하지 않아도 이 섹션은 그대로 보여야 합니다.

3. LAYER 3 | 종목 브리핑
주요 지표
- 엔비디아 흐름을 점검했습니다.
- 비트코인 ETF 흐름을 점검했습니다.

거시 지표
- 달러 인덱스를 함께 봤습니다.
"""

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )
    text = render_briefing_email_text(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert "Layer 2 · 주요 뉴스" in html
    assert "기사 형식이 완전하지 않아도 이 섹션은 그대로 보여야 합니다." in html
    assert "Layer 3 · 종목 브리핑" in html
    assert "엔비디아 흐름을 점검했습니다." in html
    assert "[LAYER 2 | 주요 뉴스]" in text
    assert "기사 형식이 완전하지 않아도 이 섹션은 그대로 보여야 합니다." in text
    assert "[LAYER 3 | 종목 브리핑]" in text
    assert "엔비디아 흐름을 점검했습니다." in text


def test_build_email_context_scopes_stock_and_macro_rows_to_layer_three_only():
    body = """Morning Market Brief (2026-03-12)

1. LAYER 1 | 오늘 한줄 판단
주요 지표
- S&P500은 610.25 (+1.20%)였습니다.
- 달러 인덱스는 99.40이었습니다.

2. LAYER 2 | 주요 뉴스
핵심 이슈
- Nvidia unveils new AI cluster | 데이터센터 투자 기대를 다시 자극했습니다. | https://www.reuters.com/world/us/example

3. LAYER 3 | 종목 브리핑
주요 지표
- NVDA | +1.20% | 데이터센터 투자 기대가 이어졌습니다. | [출처: Stooq]
- AMD | -0.80% | 반도체 종목 안에서도 차이가 있었습니다. | [출처: Stooq]

거시 지표
- 달러 인덱스는 99.40이었습니다.
- 미국 10년물 금리는 4.10%였습니다.
"""

    context = _build_email_context(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    stock_rows = context["stock_rows"]
    macro_rows = context["macro_rows"]
    assert [row.name for row in stock_rows] == ["NVDA", "AMD"]
    assert len(macro_rows) == 2
    assert "S&amp;P500" not in context["layer_one_html"]
    assert [label for label, _value in macro_rows] == ["달러 인덱스", "미국 10년물 금리"]


def test_render_briefing_email_html_does_not_repeat_stock_or_macro_values():
    body = """Morning Market Brief (2026-03-12)

1. LAYER 1 | 오늘 한줄 판단
핵심 판단
시장은 자산별로 엇갈렸습니다.

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 예시 뉴스 | 해석 문장 | https://www.reuters.com/world/us/example

3. LAYER 3 | 종목 브리핑
주요 지표
- AVGO | -4.11% | 서버 투자 기대가 둔화됐습니다. | [출처: Stooq]
- META | -3.83% | 광고 업종 전반이 약했습니다. | [출처: Stooq]

거시 지표
- 달러 인덱스는 100.49였습니다.
- 미국 10년물 금리는 4.10%였습니다.
"""

    html = render_briefing_email_html(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )
    text = render_briefing_email_text(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert html.count("AVGO") == 1
    assert html.count("META") == 1
    assert html.count("달러 인덱스") == 1
    assert html.count("미국 10년물 금리") == 1
    assert "AVGO는 전일 대비" in html
    assert "META는 전일 대비" in html
    assert "하락했습니다." in html
    assert text.count("AVGO") == 1
    assert text.count("META") == 1
    assert text.count("달러 인덱스") == 1
    assert text.count("미국 10년물 금리") == 1
    assert "AVGO는 전일 대비 4.11% 하락했습니다." in text
    assert "META는 전일 대비 3.83% 하락했습니다." in text


def test_build_email_context_formats_stock_rows_as_single_sentences():
    body = """Morning Market Brief (2026-03-12)

3. LAYER 3 | 종목 브리핑
주요 지표
- AVGO | -4.11% | 서버 투자 기대가 둔화됐습니다. | [출처: Stooq]
- BTC-USD | -0.16% | 비트코인 현물은 71,282달러였습니다. | [출처: CoinGecko]
"""

    context = _build_email_context(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    stock_rows = context["stock_rows"]
    assert [row.context_text for row in stock_rows] == [
        "AVGO는 전일 대비 4.11% 하락했습니다.",
        "비트코인은 전일 대비 0.16% 하락, 현재 71,282달러입니다.",
    ]


def test_build_email_context_dedupes_repeated_stock_and_macro_rows():
    body = """Morning Market Brief (2026-03-12)

3. LAYER 3 | 종목 브리핑
주요 지표
- AVGO | -4.11% | 서버 투자 기대가 둔화됐습니다. | [출처: Stooq]
- AVGO | -4.11% | 서버 투자 기대가 둔화됐습니다. | [출처: Stooq]

거시 지표
- 달러 인덱스는 100.49였습니다.
- 달러 인덱스는 100.49였습니다.
"""

    context = _build_email_context(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    assert [row.context_text for row in context["stock_rows"]] == [
        "AVGO는 전일 대비 4.11% 하락했습니다."
    ]
    assert [label for label, _value in context["macro_rows"]] == ["달러 인덱스"]


def test_build_email_context_omits_none_interpretation_and_dedupes_source_urls():
    body = """Morning Market Brief (2026-03-12)

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 엔비디아가 새 AI 클러스터를 공개했습니다 | None
- 같은 뉴스가 다시 들어왔습니다 | null

참고 출처
- 엔비디아가 새 AI 클러스터를 공개했습니다 — https://news.google.com/rss/articles/CBMiQWh0dHBzOi8vd3d3LnJldXRlcnMuY29tL3dvcmxkL3VzL2V4YW1wbGXSAQA?oc=5
- 같은 뉴스가 다시 들어왔습니다 — https://news.google.com/rss/articles/CBMiQWh0dHBzOi8vd3d3LnJldXRlcnMuY29tL3dvcmxkL3VzL2V4YW1wbGXSAQA?oc=5
"""

    context = _build_email_context(
        subject="미국 기술주·비트코인 브리핑 (2026-03-12)",
        body=body,
    )

    news_items = context["news_items"]
    news_source_items = context["news_source_items"]
    assert [item.interpretation for item in news_items] == ["", ""]
    assert len(news_source_items) == 1
    assert news_source_items[0].url.startswith("https://news.google.com/")


def test_split_reference_block_separates_reference_lines():
    body = SAMPLE_BRIEF + "\n\n참고 출처\n- Reuters — https://www.reuters.com/world/us/example"

    main_body, references = _split_reference_block(body)

    assert "참고 출처" not in main_body
    assert references == ["Reuters — https://www.reuters.com/world/us/example"]
