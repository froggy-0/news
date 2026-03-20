"""렌더링 테스트: 각 파셜 독립 렌더링.

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

TEMPLATE_DIR = Path("src/morning_brief/templates")
env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
    trim_blocks=True,
    lstrip_blocks=True,
)

# ---------------------------------------------------------------------------
# 공통 샘플 데이터
# ---------------------------------------------------------------------------

SAMPLE_SNAPSHOT_BADGES = [
    {"label": "S&P 500", "value": "+0.5%", "direction": "up"},
    {"label": "나스닥", "value": "-0.3%", "direction": "down"},
    {"label": "BTC", "value": "+1.2%", "direction": "up"},
    {"label": "VIX", "value": "18.5", "direction": "flat"},
]

SAMPLE_NEWS_ITEMS = [
    {
        "number": "①",
        "headline": "테스트 뉴스 헤드라인",
        "body": "뉴스 본문 내용입니다.",
        "source_name": "Reuters",
        "source_url": "https://reuters.com/example",
        "tldr": "핵심 요약",
        "source_tier": 1,
        "source_kind": "원문 기사",
        "source_label": "원문 기사 · Reuters",
    }
]

SAMPLE_BTC_DATA = {
    "spot_price": "$87,200",
    "spot_change": "+1.2%",
    "spot_direction": "up",
    "fear_greed_value": 65,
    "fear_greed_label": "탐욕",
    "etf_items": [
        {
            "ticker": "IBIT",
            "price": "52.30",
            "change_pct": "+0.8%",
            "direction": "up",
            "volume": "12.5M",
        }
    ],
    "official_snapshots": [],
    "official_total_btc": "",
    "official_total_aum": "",
    "status_text": "",
}

SAMPLE_SECTOR_MAPPING = {
    "positive": [{"ticker": "NVDA", "name": "NVDA", "reason": "AI 수요 확대"}],
    "negative": [{"ticker": "XLE", "name": "XLE", "reason": "유가 하락 압력"}],
    "neutral": [{"ticker": "GLD", "name": "GLD", "reason": "금리 동결 시 중립"}],
    "commentary": "전반적으로 기술주 중심 수혜 예상",
}

SAMPLE_EVENTS = [
    {
        "date": "3/18",
        "time": "21:30",
        "name": "소매판매",
        "expected": "+0.3%",
        "impact": 3,
        "is_today": True,
    },
    {
        "date": "3/19",
        "time": "14:00",
        "name": "FOMC 결정",
        "expected": "",
        "impact": 5,
        "is_today": False,
    },
]

SAMPLE_STOCK_INDICES = [
    {
        "ticker": "SPY",
        "name": "S&P 500",
        "price": "510.25",
        "change_pct": "+0.5%",
        "direction": "up",
        "volume": None,
    }
]

SAMPLE_STOCK_TECH = [
    {
        "ticker": "NVDA",
        "name": "NVDA",
        "price": "890.50",
        "change_pct": "+2.1%",
        "direction": "up",
        "volume": None,
    }
]

SAMPLE_MACRO_INDICATORS = [
    {
        "label": "10년물",
        "value": "4.20%",
        "change": "+8bp",
        "direction": "up",
        "is_previous": False,
        "is_anomaly": False,
        "status_text": None,
    }
]

# 이모지 패턴: V2 파셜에서 사용하면 안 되는 이모지 문자들
EMOJI_PATTERN = re.compile(
    "[\U0001f7e2\U0001f534\U0001f4f0\U0001f4ca\U0001f522\U0001f3af\U0001f4ce\U0001f1f0\U0001f1f7]"
)


# ---------------------------------------------------------------------------
# 1. 헤더 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_header_partial_renders_independently() -> None:
    """email_header.html.j2가 필요한 변수만으로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_header.html.j2")
    html = tmpl.render(
        display_date="2026년 3월 18일 화요일",
        read_time="3분 읽기",
        snapshot_badges=SAMPLE_SNAPSHOT_BADGES,
    )
    assert "미국 기술주&#183;비트코인 시장 브리핑" in html
    assert "뉴욕 마감 브리핑" in html
    assert "2026년 3월 18일 화요일" in html
    assert "3분 읽기" in html
    assert "S&P 500" in html or "S&amp;P 500" in html
    assert "나스닥" in html
    assert "BTC" in html
    assert "VIX" in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 2. 히어로 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_hero_partial_renders_independently() -> None:
    """email_hero.html.j2가 hero_summary 텍스트로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_hero.html.j2")
    html = tmpl.render(
        hero_summary="오늘 시장은 혼조세를 보였어요.",
        hero_alerts=["추가 메모"],
        hero_verdict="오늘은 관망 국면입니다.",
        hero_reason="변동성은 남아 있지만 추세가 엇갈립니다.",
        hero_kospi_impact="미국 기술주 흐름이 코스피 대형주에 선별적으로 반영될 수 있습니다.",
        hero_tone="flat",
    )
    assert "오늘은 관망 국면입니다." in html
    assert "변동성은 남아 있지만 추세가 엇갈립니다." in html
    assert "미국 기술주 흐름이 코스피 대형주에 선별적으로 반영될 수 있습니다." in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 3. 뉴스 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_news_partial_renders_independently() -> None:
    """email_news.html.j2가 샘플 뉴스 아이템으로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_news.html.j2")
    html = tmpl.render(news_items=SAMPLE_NEWS_ITEMS, news_status_text="")
    assert "테스트 뉴스 헤드라인" in html
    assert "뉴스 본문 내용입니다." in html
    assert "원문 기사 · Reuters" in html
    assert "핵심 요약" in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 4. BTC 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_btc_partial_renders_independently() -> None:
    """email_btc.html.j2가 샘플 btc_data로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_btc.html.j2")
    html = tmpl.render(btc_data=SAMPLE_BTC_DATA)
    assert "$87,200" in html
    assert "탐욕" in html
    assert "IBIT" in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 5. 마켓 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_market_partial_renders_independently() -> None:
    """email_market.html.j2가 샘플 종목/거시 데이터로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_market.html.j2")
    html = tmpl.render(
        stock_indices=SAMPLE_STOCK_INDICES,
        stock_tech=SAMPLE_STOCK_TECH,
        macro_indicators=SAMPLE_MACRO_INDICATORS,
        market_status_text="",
    )
    assert "SPY" in html
    assert "S&P 500" in html or "S&amp;P 500" in html
    assert "510.25" in html
    assert "NVDA" in html
    assert "10년물" in html
    assert "4.20%" in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 6. 섹터 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_sector_partial_renders_independently() -> None:
    """email_sector.html.j2가 샘플 sector_mapping으로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_sector.html.j2")
    html = tmpl.render(sector_mapping=SAMPLE_SECTOR_MAPPING)
    assert "NVDA" in html
    assert "AI 수요 확대" in html
    assert "XLE" in html
    assert "유가 하락 압력" in html
    assert "GLD" in html
    assert "금리 동결 시 중립" in html
    assert "전반적으로 기술주 중심 수혜 예상" in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 7. 캘린더 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_calendar_partial_renders_independently() -> None:
    """email_calendar.html.j2가 샘플 이벤트로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_calendar.html.j2")
    html = tmpl.render(event_calendar=SAMPLE_EVENTS)
    assert "소매판매" in html
    assert "FOMC 결정" in html
    assert "+0.3%" in html
    # 영향도 ■□ 표시 확인 (HTML 엔티티)
    assert "&#9632;" in html
    assert "&#9633;" in html
    assert 'role="presentation"' in html


# ---------------------------------------------------------------------------
# 8. 푸터 파셜 독립 렌더링
# ---------------------------------------------------------------------------


def test_footer_partial_renders_independently() -> None:
    """email_footer.html.j2가 최소 변수로 독립 렌더링 가능한지 확인."""
    tmpl = env.get_template("email_footer.html.j2")
    html = tmpl.render(
        news_source_items=[
            {
                "headline": "테스트 뉴스 헤드라인",
                "source_name": "Reuters",
                "source_kind": "원문 기사",
                "safe_url": "https://reuters.com/example",
            }
        ],
        market_source_lines=[
            "거시 지표: FRED, yfinance",
            "미국 지수/기술주: Stooq",
        ],
        data_quality_status="ok",
        footer_notes=[],
        unsubscribe_url="https://example.com/unsub",
        github_url="https://github.com/example",
    )
    assert "https://example.com/unsub" in html
    assert "https://github.com/example" in html
    assert "출처와 데이터" in html
    assert "Reuters" in html
    assert "FRED" in html or "&#xB370;&#xC774;&#xD130;" in html


# ---------------------------------------------------------------------------
# 9. 베이스 템플릿 role="presentation" 확인
# ---------------------------------------------------------------------------


def _build_full_context() -> dict:
    """email_base.html.j2 렌더링에 필요한 전체 컨텍스트."""
    return {
        "subject": "테스트 브리핑",
        "preheader": "S&P +0.5% · BTC $87,200",
        "display_date": "2026년 3월 18일 화요일",
        "read_time": "3분 읽기",
        "snapshot_badges": SAMPLE_SNAPSHOT_BADGES,
        "hero_summary": "오늘 시장은 혼조세를 보였어요.",
        "hero_alerts": [],
        "hero_verdict": "오늘은 관망 국면입니다.",
        "hero_reason": "변동성은 남아 있지만 추세가 엇갈립니다.",
        "hero_kospi_impact": "국내 증시는 종목별 차별화가 커질 수 있습니다.",
        "hero_tone": "flat",
        "news_items": SAMPLE_NEWS_ITEMS,
        "news_status_text": "",
        "news_source_items": [
            {
                "headline": "테스트 뉴스 헤드라인",
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
        "btc_data": SAMPLE_BTC_DATA,
        "stock_indices": SAMPLE_STOCK_INDICES,
        "stock_tech": SAMPLE_STOCK_TECH,
        "macro_indicators": SAMPLE_MACRO_INDICATORS,
        "market_status_text": "",
        "sector_mapping": SAMPLE_SECTOR_MAPPING,
        "event_calendar": SAMPLE_EVENTS,
        "data_quality_status": "ok",
        "footer_notes": [],
        "unsubscribe_url": "https://example.com/unsub",
        "github_url": "https://github.com/example",
    }


def test_base_template_has_role_presentation() -> None:
    """email_base.html.j2의 모든 <table>에 role='presentation'이 있는지 확인."""
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**_build_full_context())
    tables = re.findall(r"<table[^>]*>", html)
    assert len(tables) > 0, "테이블이 하나도 없음"
    for table_tag in tables:
        assert 'role="presentation"' in table_tag, f"role='presentation' 누락: {table_tag[:80]}"


# ---------------------------------------------------------------------------
# 10. 베이스 템플릿 lang="ko" 확인
# ---------------------------------------------------------------------------


def test_base_template_has_lang_ko() -> None:
    """email_base.html.j2의 <html> 태그에 lang='ko'가 있는지 확인."""
    tmpl = env.get_template("email_base.html.j2")
    html = tmpl.render(**_build_full_context())
    assert re.search(r'<html[^>]*lang="ko"', html), "lang='ko' 속성 누락"


# ---------------------------------------------------------------------------
# 11. V2 파셜 이모지 미사용 확인
# ---------------------------------------------------------------------------

_V2_PARTIALS = [
    (
        "email_header.html.j2",
        {
            "display_date": "2026년 3월 18일",
            "read_time": "3분 읽기",
            "snapshot_badges": SAMPLE_SNAPSHOT_BADGES,
        },
    ),
    (
        "email_hero.html.j2",
        {
            "hero_summary": "테스트 요약",
            "hero_alerts": ["경고 1"],
            "hero_verdict": "오늘은 관망 국면입니다.",
            "hero_reason": "변동성은 남아 있지만 추세가 엇갈립니다.",
            "hero_kospi_impact": "국내 증시는 종목별 차별화가 커질 수 있습니다.",
            "hero_tone": "flat",
        },
    ),
    (
        "email_news.html.j2",
        {
            "news_items": SAMPLE_NEWS_ITEMS,
            "news_status_text": "",
        },
    ),
    (
        "email_btc.html.j2",
        {
            "btc_data": SAMPLE_BTC_DATA,
        },
    ),
    (
        "email_market.html.j2",
        {
            "stock_indices": SAMPLE_STOCK_INDICES,
            "stock_tech": SAMPLE_STOCK_TECH,
            "macro_indicators": SAMPLE_MACRO_INDICATORS,
            "market_status_text": "",
        },
    ),
    (
        "email_sector.html.j2",
        {
            "sector_mapping": SAMPLE_SECTOR_MAPPING,
        },
    ),
    (
        "email_calendar.html.j2",
        {
            "event_calendar": SAMPLE_EVENTS,
        },
    ),
    (
        "email_footer.html.j2",
        {
            "news_source_items": [
                {
                    "headline": "테스트 뉴스 헤드라인",
                    "source_name": "Reuters",
                    "source_kind": "원문 기사",
                    "safe_url": "https://reuters.com/example",
                }
            ],
            "market_source_lines": [
                "거시 지표: FRED, yfinance",
                "미국 지수/기술주: Stooq",
            ],
            "data_quality_status": "ok",
            "footer_notes": [],
            "unsubscribe_url": "https://example.com/unsub",
            "github_url": "https://github.com/example",
        },
    ),
]


def test_partials_no_emoji() -> None:
    """V2 파셜들이 이모지를 사용하지 않고 HTML 엔티티만 사용하는지 확인."""
    for template_name, context in _V2_PARTIALS:
        tmpl = env.get_template(template_name)
        html = tmpl.render(**context)
        match = EMOJI_PATTERN.search(html)
        assert match is None, (
            f"{template_name}에서 이모지 발견: {match.group()!r} (U+{ord(match.group()):04X})"
        )


# ---------------------------------------------------------------------------
# 12. V2 파셜 한국어 라벨 정규화 테스트
# ---------------------------------------------------------------------------

# 각 파셜별 기대 한국어 라벨 매핑
_EXPECTED_KOREAN_LABELS: dict[str, list[str]] = {
    "email_news.html.j2": ["주요 뉴스", "시장 의미", "원문 기사"],
    "email_btc.html.j2": ["크립토", "공포탐욕", "가격", "등락", "거래량"],
    "email_sector.html.j2": ["오늘 주목 흐름", "수혜 방향", "압력 방향", "중립 / 관망"],
    "email_calendar.html.j2": ["이벤트 캘린더", "시간", "이벤트", "예상", "영향도", "오늘 발표"],
    "email_market.html.j2": ["시장 지표", "빅테크 10종", "거시 지표"],
    "email_footer.html.j2": ["출처와 데이터", "뉴스 출처", "시장 데이터", "구독 해지"],
}

# 파셜 이름 → _V2_PARTIALS 컨텍스트 매핑 (재사용)
_V2_PARTIAL_CONTEXT: dict[str, dict] = {name: ctx for name, ctx in _V2_PARTIALS}


@pytest.mark.parametrize(
    "template_name,expected_labels",
    list(_EXPECTED_KOREAN_LABELS.items()),
    ids=[t.replace(".html.j2", "") for t in _EXPECTED_KOREAN_LABELS],
)
def test_v2_partial_korean_labels(template_name: str, expected_labels: list[str]) -> None:
    """각 V2 파셜이 한국어 라벨을 실제 한국어 문자로 렌더링하는지 확인.

    Validates: Requirements 5.9, 14.4
    """
    context = _V2_PARTIAL_CONTEXT[template_name]
    tmpl = env.get_template(template_name)
    html = tmpl.render(**context)
    for label in expected_labels:
        assert label in html, f"{template_name}: 한국어 라벨 '{label}'이 렌더링 결과에 없음"


# 한국어 유니코드 범위(U+AC00~U+D7AF)에 해당하는 hex 엔티티 패턴
_KOREAN_HEX_ENTITY_RE = re.compile(
    r"&#x[Aa][CcDdEeFf][0-9A-Fa-f]{2};"
    r"|&#x[Bb][0-9A-Fa-f]{3};"
    r"|&#x[Cc][0-9A-Fa-f]{3};"
    r"|&#x[Dd][0-7][0-9A-Fa-f]{2};"
)


def test_v2_partials_no_korean_hex_entities() -> None:
    """모든 V2 파셜 렌더링 결과에 한국어 문자(U+AC00~U+D7AF) hex 엔티티가 남아있지 않은지 확인.

    &#9632; 같은 기호 엔티티는 허용하고, 한국어 글자 엔티티만 검출한다.

    Validates: Requirements 5.9, 14.4
    """
    for template_name, context in _V2_PARTIALS:
        tmpl = env.get_template(template_name)
        html = tmpl.render(**context)
        match = _KOREAN_HEX_ENTITY_RE.search(html)
        assert match is None, f"{template_name}: 한국어 hex 엔티티 잔존 — {match.group()!r}"
