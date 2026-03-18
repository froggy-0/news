"""통합 테스트: _build_email_context_v2() 전체 흐름.

Validates: Requirements 6.2, 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

from morning_brief.emailer import _build_email_context_v2

# ---------------------------------------------------------------------------
# 공통 샘플 데이터
# ---------------------------------------------------------------------------

SAMPLE_BODY = """\
Morning Market Brief (2026-03-18)
0. 오늘의 핵심
오늘 시장은 혼조세를 보였어요.

1. 거시 지표 Dashboard
- 10년물: 4.20% (+0.08%p)
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
        "bitcoin": {
            "spot": {"price": 87200, "change_pct": 1.2},
            "fear_greed_value": 65,
            "etf_points": [],
            "official_etf_daily_flow_btc": 150,
        },
        "macro": [
            {
                "label": "VIX",
                "canonical_key": "vix",
                "ticker": "VIX",
                "price": 18.5,
                "change_pct": None,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Expected keys in the returned context dict
# ---------------------------------------------------------------------------

EXPECTED_KEYS = {
    "subject",
    "preheader",
    "display_date",
    "read_time",
    "snapshot_badges",
    "hero_summary",
    "hero_alerts",
    "macro_indicators",
    "stock_indices",
    "stock_tech",
    "btc_data",
    "issue_briefings",
    "news_items",
    "sector_mapping",
    "weekly_context",
    "sonar_analyses",
    "x_reactions",
    "event_calendar",
    "data_quality_status",
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


def test_build_email_context_v2_ok_status_empty_footer_notes() -> None:
    """status=ok 일 때 footer_notes는 빈 리스트여야 한다."""
    packet = _make_packet(status="ok", footer_notes=["이 노트는 무시돼야 함"])
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, packet)
    assert ctx["footer_notes"] == []


def test_build_email_context_v2_degraded_status_includes_footer_notes() -> None:
    """status=degraded 일 때 footer_notes가 포함돼야 한다."""
    notes = ["VIX 데이터 지연", "원/달러 캐시 대체"]
    packet = _make_packet(status="degraded", footer_notes=notes)
    ctx = _build_email_context_v2("제목", SAMPLE_BODY, packet)
    assert ctx["footer_notes"] == notes
    assert ctx["data_quality_status"] == "degraded"


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
    assert news[1]["headline"] == "연준 금리 동결 시사"
    assert news[1]["source_name"] == "Bloomberg"


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
    assert len(badges) <= 4

    labels = [b["label"] for b in badges]
    assert "S&P 500" in labels
    assert "BTC" in labels
    assert "VIX" in labels

    for badge in badges:
        assert "label" in badge
        assert "value" in badge
        assert "direction" in badge
        assert badge["direction"] in ("up", "down", "flat")
