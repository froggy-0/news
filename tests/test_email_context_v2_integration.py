"""통합 테스트: _build_email_context_v2() 전체 흐름.

Validates: Requirements 6.2, 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import logging

from morning_brief.emailer import _build_email_context_v2

# ---------------------------------------------------------------------------
# 공통 샘플 데이터
# ---------------------------------------------------------------------------

SAMPLE_BODY = """\
SOVEREIGN BRIEF (2026-03-18)
0. 오늘의 핵심
오늘 시장은 혼조세를 보였어요.

1. 거시 지표 Dashboard
- 10년물: 4.20% (전일 대비 +8bp)
- DXY: 103.5 (-0.3%)

2. 미국 증시
SPY 510.25 +0.5%
QQQ 440.10 -0.3%

빅테크 10종
NVDA 890.50 +2.1%
AAPL 172.30 -0.8%

3. BTC & 크립토
BTC 현물 $87,200 (+1.2%)

4-1. 이슈 브리핑
AI 투자 확대
엔비디아가 새로운 AI 칩을 발표했어요. 데이터센터 수요가 계속 늘어나고 있거든요.

4-2. 핵심 뉴스 5선
① 엔비디아 AI 칩 발표 — Reuters
AI 반도체 시장에서 큰 변화가 예상돼요.
→ 원문 보기 https://reuters.com/example1
핵심 한줄: 엔비디아 AI 칩 신제품 발표

② 연준 금리 동결 시사 — Bloomberg
파월 의장이 당분간 금리를 유지하겠다고 했어요.
→ 원문 보기 https://bloomberg.com/example2
핵심 한줄: 연준 금리 동결 기조 유지

4-3. 섹터/자산 영향 매핑
수혜 방향
- NVDA AI 수요 확대로 수혜
압력 방향
- XLE 유가 하락 압력
중립 / 관망
- GLD 금리 동결 시 중립

5-1. 주간 맥락 연결
이번 주는 FOMC 회의가 핵심이에요.

6. 이벤트 캘린더
오늘 발표 (3/18)
21:30 소매판매 +0.3% ■■■□□
이번 주
3/19 14:00 FOMC 결정 ■■■■■
"""


def _make_packet(
    status: str = "ok",
    footer_notes: list[str] | None = None,
) -> dict:
    return {
        "data_quality": {"status": status},
        "data_footer_notes": footer_notes or [],
        "us_indices": [
            {"ticker": "SPY", "change_pct": 0.5},
            {"ticker": "QQQ", "change_pct": -0.3},
        ],
        "korea_watch": [
            {
                "canonical_key": "usdkrw",
                "label": "원/달러 환율",
                "price": 1330.0,
                "change_pct": 0.2,
            },
            {
                "canonical_key": "nq_futures",
                "label": "나스닥 선물",
                "price": 20150.0,
                "change_pct": -0.4,
            },
        ],
        "bitcoin": {
            "spot": {"price": 87200, "change_pct": 1.2},
            "fear_greed_value": 65,
            "fear_greed_label": "탐욕",
            "etf_points": [],
        },
        "macro": [
            {
                "label": "미국 10년물",
                "canonical_key": "us10y",
                "ticker": "DGS10",
                "price": 4.2,
                "change_bps": 8,
            },
            {
                "label": "달러 인덱스",
                "canonical_key": "dxy",
                "ticker": "DX-Y.NYB",
                "price": 103.5,
                "change_pct": -0.3,
            },
            {
                "label": "VIX",
                "canonical_key": "vix",
                "ticker": "VIX",
                "price": 18.5,
                "change_pct": None,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Expected keys in the returned context dict
# ---------------------------------------------------------------------------

EXPECTED_KEYS = {
    "subject",
    "preheader",
    "mail_theme",
    "display_date",
    "read_time",
    "snapshot_badges",
    "header_signal_label",
    "header_signal_tone",
    "hero_summary",
    "hero_alerts",
    "hero_verdict",
    "hero_reason",
    "hero_kospi_impact",
    "hero_tone",
    "macro_indicators",
    "stock_indices",
    "stock_tech",
    "btc_data",
    "news_status_text",
    "market_status_text",
    "issue_briefings",
    "news_items",
    "news_source_items",
    "market_source_lines",
    "sector_mapping",
    "weekly_context",
    "sonar_analyses",
    "x_reactions",
    "event_calendar",
    "data_quality_status",
    "data_quality_line",
    "footer_notes",
    "unsubscribe_url",
    "github_url",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_email_context_v2_all_keys_present() -> None:
    """모든 변수 키가 반환 딕셔너리에 존재하는지 확인."""
    ctx = _build_email_context_v2("테스트 제목", SAMPLE_BODY, _make_packet())
    assert set(ctx.keys()) == EXPECTED_KEYS


def test_build_email_context_v2_includes_quiet_signal_theme() -> None:
    ctx = _build_email_context_v2("테스트 제목", SAMPLE_BODY, _make_packet())
    theme = ctx["mail_theme"]
    assert isinstance(theme, dict)
    assert theme["name"] == "quiet-signal"
    assert theme["colors"]["accentCyan"] == "#00ffff"
    assert theme["colors"]["accentGreen"] == "#00ff66"


def test_build_email_context_v2_ok_status_empty_footer_notes() -> None:
    """status=ok 일 때 footer_notes는 빈 리스트여야 한다."""
    packet = _make_packet(status="ok", footer_notes=["이 노트는 무시돼야 함"])
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, packet)
    assert ctx["footer_notes"] == []
    assert ctx["data_quality_line"] == "데이터 품질 상태: ok"


def test_build_email_context_v2_degraded_status_includes_footer_notes() -> None:
    """status=degraded 일 때 footer_notes가 포함돼야 한다."""
    notes = ["VIX 데이터 지연", "원/달러 캐시 대체"]
    packet = _make_packet(status="degraded", footer_notes=notes)
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, packet)
    assert ctx["footer_notes"] == notes
    assert ctx["data_quality_status"] == "degraded"
    assert ctx["data_quality_line"] == "데이터 품질 상태: degraded"


def test_build_email_context_v2_critical_status_subject_prefix() -> None:
    """status=critical이고 subject가 빈 문자열이면 제목에 '[데이터 참고]'가 포함돼야 한다."""
    notes = ["심각한 데이터 오류"]
    packet = _make_packet(status="critical", footer_notes=notes)
    ctx = _build_email_context_v2("", SAMPLE_BODY, packet)
    assert "[데이터 참고]" in str(ctx["subject"])
    assert ctx["footer_notes"] == notes


def test_build_email_context_v2_parses_news_items() -> None:
    """뉴스 아이템이 올바르게 파싱되는지 확인."""
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, _make_packet())
    news = ctx["news_items"]
    assert isinstance(news, list)
    assert len(news) == 2
    assert news[0]["headline"] == "엔비디아 AI 칩 발표"
    assert news[0]["source_name"] == "Reuters"
    assert news[0]["source_url"] == "https://reuters.com/example1"
    assert news[0]["source_label"] == "원문 기사 · Reuters"
    assert news[1]["headline"] == "연준 금리 동결 시사"
    assert news[1]["source_name"] == "Bloomberg"


def test_build_email_context_v2_core_status_messages_are_empty_when_data_exists() -> None:
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, _make_packet())
    assert ctx["news_status_text"] == ""
    assert ctx["market_status_text"] == ""


def test_build_email_context_v2_uses_packet_market_data_without_parse_fallback(caplog) -> None:
    minimal_body = """\
SOVEREIGN BRIEF (2026-03-18)
0. 오늘의 핵심
오늘 시장은 혼조세를 보였어요.
"""
    packet = _make_packet()
    packet["tech_stocks"] = [{"ticker": "NVDA", "label": "엔비디아", "change_pct": 2.1}]

    with caplog.at_level(logging.WARNING, logger="morning_brief.emailer"):
        ctx = _build_email_context_v2("제목", minimal_body, packet)

    assert [item["ticker"] for item in ctx["stock_indices"]] == ["SPY", "QQQ"]
    assert [item["ticker"] for item in ctx["stock_tech"]] == ["NVDA"]
    assert [item["label"] for item in ctx["macro_indicators"]] == [
        "미국 10년물",
        "달러 인덱스",
        "VIX",
    ]
    assert not any("packet 값으로" in record.message for record in caplog.records)


def test_build_email_context_v2_builds_hero_metadata_and_sources() -> None:
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, _make_packet())
    assert ctx["hero_verdict"] == "오늘 시장은 혼조세를 보였어요."
    assert ctx["hero_reason"] == ""
    assert ctx["hero_kospi_impact"] == ""
    assert ctx["hero_tone"] == "flat"
    assert ctx["header_signal_label"] == "시장 점검"
    assert ctx["header_signal_tone"] == "flat"
    news_sources = ctx["news_source_items"]
    assert isinstance(news_sources, list)
    assert news_sources[0].source_name == "Reuters"
    assert news_sources[0].source_kind == "원문 기사"
    assert ctx["market_source_lines"] == [
        "거시 지표: FRED, yfinance",
        "미국 지수/기술주: KIS",
        "비트코인: CoinGecko",
        "X 시그널: Grok",
    ]


def test_build_email_context_v2_parses_sector_mapping() -> None:
    """섹터 매핑이 올바르게 파싱되는지 확인."""
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, _make_packet())
    mapping = ctx["sector_mapping"]
    assert mapping is not None
    assert len(mapping["positive"]) >= 1
    assert len(mapping["negative"]) >= 1
    assert len(mapping["neutral"]) >= 1


def test_build_email_context_v2_snapshot_badges() -> None:
    """스냅샷 배지가 packet 데이터로부터 올바르게 생성되는지 확인."""
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, _make_packet())
    badges = ctx["snapshot_badges"]
    assert isinstance(badges, list)
    assert len(badges) == 6

    labels = [b["label"] for b in badges]
    assert "미국 10년물" in labels
    assert "원/달러" in labels
    assert "나스닥 선물" in labels
    assert "BTC 현물" in labels
    assert "VIX" in labels

    for badge in badges:
        assert "label" in badge
        assert "value" in badge
        assert "change" in badge
        assert "direction" in badge
        assert "status_text" in badge
        assert badge["direction"] in ("up", "down", "flat")
