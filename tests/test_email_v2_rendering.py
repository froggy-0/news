"""렌더링 테스트: 각 V2 파셜 독립 렌더링.

Validates: Requirements 14.1, 14.3, 14.4, 16.3
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Jinja2 환경 설정
# ---------------------------------------------------------------------------

EMAIL_TEMPLATE_DIR = Path("src/morning_brief/templates")

env = Environment(
    loader=FileSystemLoader(str(EMAIL_TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
    trim_blocks=True,
    lstrip_blocks=True,
)

# ---------------------------------------------------------------------------
# 공통 샘플 데이터
# ---------------------------------------------------------------------------

SAMPLE_CONTEXT = {
    "subject": "테스트 브리핑",
    "preheader": "테스트 프리헤더",
    "display_date": "2026년 3월 18일 수요일",
    "read_time": "3분 읽기",
    "snapshot_badges": [
        {"label": "S&P 500", "value": "+0.5%", "direction": "up"},
        {"label": "나스닥", "value": "-0.3%", "direction": "down"},
        {"label": "BTC", "value": "+1.2%", "direction": "up"},
        {"label": "VIX", "value": "18.5", "direction": "flat"},
    ],
    "hero_summary": "오늘 시장은 혼조세를 보였어요.",
    "hero_alerts": ["VIX가 평소보다 높아요"],
    "hero_verdict": "오늘은 관망 국면입니다.",
    "hero_reason": "VIX가 평소보다 높아 변동성이 남아 있습니다.",
    "hero_kospi_impact": "미국 장세가 엇갈려 코스피는 종목별 차별화가 커질 수 있습니다.",
    "hero_tone": "flat",
    "macro_indicators": [
        {
            "label": "10년물",
            "value": "4.20%",
            "change": "+8bp",
            "direction": "up",
            "is_previous": False,
            "is_anomaly": False,
            "status_text": None,
        },
    ],
    "stock_indices": [
        {
            "ticker": "SPY",
            "name": "S&P 500",
            "price": "510.25",
            "change_pct": "+0.5%",
            "direction": "up",
            "volume": None,
        },
    ],
    "stock_tech": [
        {
            "ticker": "NVDA",
            "name": "엔비디아",
            "price": "890.50",
            "change_pct": "+2.1%",
            "direction": "up",
            "volume": None,
        },
    ],
    "btc_data": {
        "spot_price": "$87,200",
        "spot_change": "+1.2%",
        "spot_direction": "up",
        "fear_greed_value": 65,
        "fear_greed_label": "탐욕",
        "etf_items": [
            {
                "ticker": "IBIT",
                "price": "52.30",
                "change_pct": "+1.5%",
                "direction": "up",
                "volume": "25M",
            }
        ],
        "official_snapshots": [],
        "official_total_btc": "",
        "official_total_aum": "",
        "status_text": "",
    },
    "issue_briefings": [{"topic": "AI 투자", "body": "엔비디아가 새 칩을 발표했어요."}],
    "news_items": [
        {
            "number": "①",
            "headline": "엔비디아 AI 칩 발표",
            "body": "AI 반도체 시장에서 큰 변화가 예상돼요.",
            "source_name": "Reuters",
            "source_url": "https://reuters.com/example",
            "tldr": "엔비디아 AI 칩 신제품 발표",
            "source_tier": 1,
            "source_kind": "원문 기사",
            "source_label": "원문 기사 · Reuters",
        },
    ],
    "news_source_items": [
        {
            "headline": "엔비디아 AI 칩 발표",
            "source_name": "Reuters",
            "source_kind": "원문 기사",
            "safe_url": "https://reuters.com/example",
        }
    ],
    "market_source_lines": [
        "거시 지표: FRED, yfinance",
        "미국 지수/기술주: Stooq",
        "비트코인: CoinGecko",
        "X 시그널: Grok",
    ],
    "sector_mapping": {
        "positive": [{"ticker": "NVDA", "name": "NVDA", "reason": "AI 수요 확대"}],
        "negative": [{"ticker": "XLE", "name": "XLE", "reason": "유가 하락 압력"}],
        "neutral": [{"ticker": "GLD", "name": "GLD", "reason": "금리 동결 시 중립"}],
        "commentary": "AI 관련주 수혜 예상",
    },
    "weekly_context": "이번 주는 FOMC 회의가 핵심이에요.",
    "sonar_analyses": None,
    "x_reactions": None,
    "news_status_text": "",
    "market_status_text": "",
    "event_calendar": [
        {
            "date": "3/18",
            "time": "21:30",
            "name": "소매판매",
            "expected": "+0.3%",
            "impact": 3,
            "is_today": True,
        },
    ],
    "data_quality_status": "ok",
    "footer_notes": [],
    "unsubscribe_url": "mailto:test@example.com",
    "github_url": "https://github.com/test/repo",
}

# 이모지 패턴: V2 템플릿에서 사용하면 안 되는 이모지 문자들
EMOJI_PATTERN = re.compile(
    "["
    "\U0001f7e2"  # 🟢
    "\U0001f534"  # 🔴
    "\U0001f4f0"  # 📰
    "\U0001f4ca"  # 📊
    "\U0001f522"  # 🔢
    "\U0001f3af"  # 🎯
    "\U0001f4ce"  # 📎
    "\U0001f1f0"  # 🇰 (regional indicator K)
    "\U0001f1f7"  # 🇷 (regional indicator R)
    "]"
)


# ---------------------------------------------------------------------------
# 파셜별 최소 변수 매핑
# ---------------------------------------------------------------------------

PARTIAL_CONFIGS = [
    (
        "email_header.html.j2",
        {
            "display_date": SAMPLE_CONTEXT["display_date"],
            "read_time": SAMPLE_CONTEXT["read_time"],
            "snapshot_badges": SAMPLE_CONTEXT["snapshot_badges"],
        },
    ),
    (
        "email_hero.html.j2",
        {
            "hero_summary": SAMPLE_CONTEXT["hero_summary"],
            "hero_alerts": SAMPLE_CONTEXT["hero_alerts"],
            "hero_verdict": SAMPLE_CONTEXT["hero_verdict"],
            "hero_reason": SAMPLE_CONTEXT["hero_reason"],
            "hero_kospi_impact": SAMPLE_CONTEXT["hero_kospi_impact"],
            "hero_tone": SAMPLE_CONTEXT["hero_tone"],
        },
    ),
    (
        "email_news.html.j2",
        {
            "news_items": SAMPLE_CONTEXT["news_items"],
            "news_status_text": SAMPLE_CONTEXT["news_status_text"],
        },
    ),
    (
        "email_btc.html.j2",
        {
            "btc_data": SAMPLE_CONTEXT["btc_data"],
        },
    ),
    (
        "email_market.html.j2",
        {
            "stock_indices": SAMPLE_CONTEXT["stock_indices"],
            "stock_tech": SAMPLE_CONTEXT["stock_tech"],
            "macro_indicators": SAMPLE_CONTEXT["macro_indicators"],
            "market_status_text": SAMPLE_CONTEXT["market_status_text"],
        },
    ),
    (
        "email_sector.html.j2",
        {
            "sector_mapping": SAMPLE_CONTEXT["sector_mapping"],
        },
    ),
    (
        "email_calendar.html.j2",
        {
            "event_calendar": SAMPLE_CONTEXT["event_calendar"],
        },
    ),
    (
        "email_footer.html.j2",
        {
            "news_source_items": SAMPLE_CONTEXT["news_source_items"],
            "market_source_lines": SAMPLE_CONTEXT["market_source_lines"],
            "data_quality_status": SAMPLE_CONTEXT["data_quality_status"],
            "footer_notes": SAMPLE_CONTEXT["footer_notes"],
            "unsubscribe_url": SAMPLE_CONTEXT["unsubscribe_url"],
            "github_url": SAMPLE_CONTEXT["github_url"],
        },
    ),
]


# ---------------------------------------------------------------------------
# 1. 파라미터화 테스트: 각 파셜 독립 렌더링
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template_name,context",
    PARTIAL_CONFIGS,
    ids=[cfg[0].replace(".html.j2", "") for cfg in PARTIAL_CONFIGS],
)
def test_each_partial_renders_independently(template_name: str, context: dict) -> None:
    """각 파셜 파일이 필요한 변수만으로 독립 렌더링 가능한지 확인.

    Validates: Requirements 16.3
    """
    tmpl = env.get_template(template_name)
    html = tmpl.render(**context)
    assert len(html.strip()) > 0, f"{template_name} 렌더링 결과가 비어있음"


# ---------------------------------------------------------------------------
# 2. 베이스 템플릿 lang="ko" 확인
# ---------------------------------------------------------------------------


def test_base_template_has_lang_ko() -> None:
    """email_base.html.j2의 <html> 태그에 lang='ko'가 있는지 확인.

    Validates: Requirements 14.4
    """
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**SAMPLE_CONTEXT)
    assert re.search(r'<html[^>]*lang="ko"', html), "lang='ko' 속성 누락"


# ---------------------------------------------------------------------------
# 3. 모든 테이블에 role="presentation" 확인
# ---------------------------------------------------------------------------


def test_all_tables_have_role_presentation() -> None:
    """email_base.html.j2 렌더링 결과의 모든 <table>에 role='presentation'이 있는지 확인.

    Validates: Requirements 14.1
    """
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**SAMPLE_CONTEXT)
    tables = re.findall(r"<table[^>]*>", html)
    assert len(tables) > 0, "테이블이 하나도 없음"
    for table_tag in tables:
        assert 'role="presentation"' in table_tag, f"role='presentation' 누락: {table_tag[:80]}"


# ---------------------------------------------------------------------------
# 4. V2 템플릿 이모지 미사용 확인
# ---------------------------------------------------------------------------


def test_v2_templates_no_emoji() -> None:
    """email_base.html.j2 전체 렌더링 결과에 이모지가 없는지 확인 (HTML 엔티티만 사용).

    Validates: Requirements 14.3
    """
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**SAMPLE_CONTEXT)
    match = EMOJI_PATTERN.search(html)
    assert match is None, (
        f"V2 템플릿에서 이모지 발견: {match.group()!r} (U+{ord(match.group()):04X})"
    )


# ---------------------------------------------------------------------------
# 5. 접근성: 방향 기호가 색상과 함께 사용되는지 확인
# ---------------------------------------------------------------------------


def _build_full_context() -> dict:
    """email_base.html.j2 렌더링에 필요한 전체 컨텍스트 (SAMPLE_CONTEXT 래퍼)."""
    return dict(SAMPLE_CONTEXT)


def test_direction_symbols_accompany_colors() -> None:
    """상승/하락/보합 배지에 방향 기호(▲/▼/—)가 색상과 함께 사용되는지 확인.

    색상만으로 방향 정보를 전달하지 않아야 한다.

    Validates: Requirements 14.2, 14.3
    """
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**_build_full_context())

    # 방향 기호 HTML 엔티티가 존재하는지 확인
    assert "&#9650;" in html, "상승 방향 기호(▲, &#9650;) 누락"
    assert "&#9660;" in html, "하락 방향 기호(▼, &#9660;) 누락"
    assert "&#8212;" in html, "보합 방향 기호(—, &#8212;) 누락"

    # 상승 배경색(#dcfce7) 근처에 ▲ 기호가 있는지 확인
    up_badge_pattern = re.compile(r"#dcfce7.*?&#9650;|&#9650;.*?#dcfce7", re.DOTALL)
    assert up_badge_pattern.search(html), (
        "상승 배지: 녹색 배경(#dcfce7)과 ▲ 기호가 함께 사용되지 않음"
    )

    # 하락 배경색(#fef2f2) 근처에 ▼ 기호가 있는지 확인
    down_badge_pattern = re.compile(r"#fef2f2.*?&#9660;|&#9660;.*?#fef2f2", re.DOTALL)
    assert down_badge_pattern.search(html), (
        "하락 배지: 적색 배경(#fef2f2)과 ▼ 기호가 함께 사용되지 않음"
    )

    # 보합 배경색(#f3f4f6) 근처에 — 기호가 있는지 확인
    flat_badge_pattern = re.compile(r"#f3f4f6.*?&#8212;|&#8212;.*?#f3f4f6", re.DOTALL)
    assert flat_badge_pattern.search(html), (
        "보합 배지: 회색 배경(#f3f4f6)과 — 기호가 함께 사용되지 않음"
    )


# ---------------------------------------------------------------------------
# 6. 접근성: CSS ::before 가상 요소 미사용 확인
# ---------------------------------------------------------------------------


def test_no_css_before_pseudo_elements() -> None:
    """email_base.html.j2에서 CSS ::before/:before 가상 요소를 사용하지 않는지 확인.

    Outlook에서 지원되지 않으므로 사용 금지.

    Validates: Requirements 14.3, 8.8
    """
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**_build_full_context())

    # <style> 블록 내에서 ::before 또는 :before 확인
    style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL)
    for block in style_blocks:
        assert "::before" not in block, "<style> 블록에서 ::before 가상 요소 발견"
        assert ":before" not in block.replace("::before", ""), (
            "<style> 블록에서 :before 가상 요소 발견"
        )

    # 인라인 스타일에서 content: 속성 확인
    inline_styles = re.findall(r'style="([^"]*)"', html)
    for style in inline_styles:
        assert "content:" not in style.lower(), (
            f"인라인 스타일에서 content: 속성 발견: {style[:80]}"
        )


# ---------------------------------------------------------------------------
# 7. 접근성: SVG 인라인 미사용 확인
# ---------------------------------------------------------------------------


def test_no_svg_inline() -> None:
    """email_base.html.j2에서 인라인 SVG를 사용하지 않는지 확인.

    Outlook에서 지원되지 않으므로 사용 금지.

    Validates: Requirements 14.3, 8.8
    """
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**_build_full_context())

    assert "<svg" not in html.lower(), "인라인 SVG(<svg) 태그 발견"


# ---------------------------------------------------------------------------
# 8. 스냅샷 테스트: 전체 HTML 출력 구조 검증
# ---------------------------------------------------------------------------


class TestSnapshotFullHtmlOutput:
    """전체 HTML 렌더링 스냅샷 검증.

    Validates: Requirements 8.3, 8.5
    """

    @pytest.fixture()
    def rendered_html(self) -> str:
        """SAMPLE_CONTEXT로 email_base.html.j2 전체 렌더링."""
        tmpl = env.get_template("email_base.html.j2")
        return tmpl.render(**SAMPLE_CONTEXT)

    # -- 기본 구조 --

    def test_rendered_html_is_nonempty(self, rendered_html: str) -> None:
        """렌더링 결과가 비어있지 않고 기본 HTML 구조를 포함한다."""
        assert len(rendered_html.strip()) > 0
        assert "<!doctype html>" in rendered_html.lower()
        assert "<html" in rendered_html
        assert "</html>" in rendered_html
        assert "<head>" in rendered_html
        assert "<body" in rendered_html

    # -- 라이트 모드 CSS 클래스 존재 --

    @pytest.mark.parametrize(
        "css_class",
        ["card", "text-strong", "text-body", "text-muted", "badge-up", "badge-down", "badge-flat"],
    )
    def test_light_mode_css_classes_exist(self, rendered_html: str, css_class: str) -> None:
        """라이트 모드 CSS 클래스가 HTML 출력에 존재한다."""
        assert css_class in rendered_html, f"라이트 모드 CSS 클래스 '{css_class}' 누락"

    # -- 다크 모드 CSS 규칙 --

    def test_dark_mode_media_query_exists(self, rendered_html: str) -> None:
        """<style> 블록에 prefers-color-scheme:dark 미디어 쿼리가 존재한다."""
        assert re.search(r"prefers-color-scheme\s*:\s*dark", rendered_html), (
            "다크 모드 미디어 쿼리(prefers-color-scheme:dark) 누락"
        )

    @pytest.mark.parametrize(
        "dark_color,description",
        [
            ("#14532d", "다크 모드 상승 배경색"),
            ("#450a0a", "다크 모드 하락 배경색"),
            ("#1f2937", "다크 모드 보합 배경색"),
        ],
    )
    def test_dark_mode_color_overrides(
        self, rendered_html: str, dark_color: str, description: str
    ) -> None:
        """다크 모드 색상 오버라이드가 스타일 블록에 존재한다."""
        style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", rendered_html, re.DOTALL)
        combined_styles = " ".join(style_blocks)
        assert dark_color in combined_styles, f"{description}({dark_color})이 <style> 블록에 누락"

    # -- 인라인 스타일 우선 적용 --

    def test_inline_styles_on_body(self, rendered_html: str) -> None:
        """<body> 태그에 인라인 style 속성이 존재한다."""
        body_match = re.search(r"<body[^>]*>", rendered_html)
        assert body_match, "<body> 태그를 찾을 수 없음"
        assert 'style="' in body_match.group(0), "<body>에 인라인 style 속성 누락"

    def test_inline_styles_on_tables(self, rendered_html: str) -> None:
        """주요 <table> 태그에 인라인 style 속성이 존재한다."""
        tables = re.findall(r"<table[^>]*>", rendered_html)
        styled_tables = [t for t in tables if 'style="' in t]
        assert len(styled_tables) > 0, "인라인 style이 적용된 <table>이 없음"
        # 대부분의 테이블에 인라인 스타일이 있어야 함
        ratio = len(styled_tables) / len(tables)
        assert ratio >= 0.5, f"테이블 중 {ratio:.0%}만 인라인 style 보유 (50% 이상 필요)"

    def test_inline_styles_on_td_elements(self, rendered_html: str) -> None:
        """주요 <td> 태그에 인라인 style 속성이 존재한다."""
        tds = re.findall(r"<td[^>]*>", rendered_html)
        styled_tds = [t for t in tds if 'style="' in t]
        assert len(styled_tds) > 0, "인라인 style이 적용된 <td>가 없음"

    def test_inline_styles_on_div_elements(self, rendered_html: str) -> None:
        """주요 <div> 태그에 인라인 style 속성이 존재한다."""
        divs = re.findall(r"<div[^>]*>", rendered_html)
        styled_divs = [d for d in divs if 'style="' in d]
        assert len(styled_divs) > 0, "인라인 style이 적용된 <div>가 없음"

    # -- 주요 섹션 포함 확인 --

    def test_contains_header_section(self, rendered_html: str) -> None:
        """헤더 섹션 콘텐츠가 포함되어 있다."""
        assert "미국 기술주&#183;비트코인 시장 브리핑" in rendered_html
        assert "뉴욕 마감 브리핑" in rendered_html
        assert SAMPLE_CONTEXT["display_date"] in rendered_html
        assert SAMPLE_CONTEXT["read_time"] in rendered_html

    def test_contains_hero_section(self, rendered_html: str) -> None:
        """히어로(핵심 요약) 섹션 콘텐츠가 포함되어 있다."""
        assert SAMPLE_CONTEXT["hero_verdict"] in rendered_html
        assert SAMPLE_CONTEXT["hero_reason"] in rendered_html
        assert SAMPLE_CONTEXT["hero_kospi_impact"] in rendered_html

    def test_contains_news_section(self, rendered_html: str) -> None:
        """뉴스 섹션 콘텐츠가 포함되어 있다."""
        news = SAMPLE_CONTEXT["news_items"][0]
        assert news["headline"] in rendered_html
        assert news["source_label"] in rendered_html

    def test_contains_btc_section(self, rendered_html: str) -> None:
        """BTC 섹션 콘텐츠가 포함되어 있다."""
        btc = SAMPLE_CONTEXT["btc_data"]
        assert btc["spot_price"] in rendered_html
        assert btc["fear_greed_label"] in rendered_html

    def test_contains_market_section(self, rendered_html: str) -> None:
        """종목/거시 지표 섹션 콘텐츠가 포함되어 있다."""
        idx = SAMPLE_CONTEXT["stock_indices"][0]
        assert idx["ticker"] in rendered_html
        tech = SAMPLE_CONTEXT["stock_tech"][0]
        assert tech["ticker"] in rendered_html

    def test_contains_sector_section(self, rendered_html: str) -> None:
        """섹터 매핑 섹션 콘텐츠가 포함되어 있다."""
        sector = SAMPLE_CONTEXT["sector_mapping"]
        assert sector["positive"][0]["ticker"] in rendered_html
        assert sector["negative"][0]["ticker"] in rendered_html
        assert sector["neutral"][0]["ticker"] in rendered_html

    def test_contains_calendar_section(self, rendered_html: str) -> None:
        """이벤트 캘린더 섹션 콘텐츠가 포함되어 있다."""
        event = SAMPLE_CONTEXT["event_calendar"][0]
        assert event["name"] in rendered_html

    def test_contains_footer_section(self, rendered_html: str) -> None:
        """Footer 섹션 콘텐츠가 포함되어 있다."""
        assert SAMPLE_CONTEXT["github_url"] in rendered_html
        assert "출처와 데이터" in rendered_html
        assert SAMPLE_CONTEXT["news_source_items"][0]["source_name"] in rendered_html
