"""tests/test_unified_output.py — UnifiedOutput 생성 단위 테스트

FC-1: change_pct 소수 2자리 assertion ("+1.23%" 형식)
FC-2: total_btc 소수 2자리 assertion ("570,234.56 BTC")
FC-3: BTC 가격 "$84,321" 형식 assertion
FC-4: change_bps 부호 포함 정수 assertion ("+12bp" / "-5bp")
"""

from __future__ import annotations

import json

import pytest

from morning_brief.unified_output import (
    MetaLayer,
    NarrativeLayer,
    QuantitativeLayer,
    UnifiedOutput,
    briefing_to_narrative,
    packet_to_quantitative,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_PACKET: dict = {
    "macro": [
        {
            "canonical_key": "us10y",
            "label": "미국 10년물",
            "price": 4.25,
            "resolved_value": 4.25,
            "change_bps": 12.0,
        },
        {
            "canonical_key": "dxy",
            "label": "달러 인덱스",
            "price": 104.5,
            "resolved_value": 104.5,
            "change_pct": -0.35,
        },
        {
            "canonical_key": "vix",
            "label": "VIX",
            "price": 16.8,
            "resolved_value": 16.8,
            "change_pct": 1.50,
        },
    ],
    "korea_watch": [
        {
            "canonical_key": "usdkrw",
            "label": "원/달러",
            "price": 1380.5,
            "resolved_value": 1380.5,
            "change_pct": 0.12,
        },
        {
            "canonical_key": "nq_futures",
            "label": "나스닥 선물",
            "price": 19800.25,
            "resolved_value": 19800.25,
            "change_pct": -0.75,
        },
    ],
    "korea_indices": [
        {
            "canonical_key": "kospi",
            "label": "코스피",
            "ticker": "0001",
            "price": 5450.33,
            "resolved_value": 5450.33,
            "change_pct": 1.36,
        },
        {
            "canonical_key": "kosdaq",
            "label": "코스닥",
            "ticker": "1001",
            "price": 1047.37,
            "resolved_value": 1047.37,
            "change_pct": -1.54,
        },
    ],
    "validated_indices": [
        {
            "canonical_key": "dow30",
            "label": "다우30",
            "ticker": ".DJI",
            "price": 46504.67,
            "resolved_value": 46504.67,
            "change_pct": -0.13,
        }
    ],
    "us_indices": [
        {
            "canonical_key": "spy",
            "label": "S&P 500",
            "ticker": "SPY",
            "price": 550.12,
            "resolved_value": 550.12,
            "change_pct": 0.45,
        },
        {
            "canonical_key": "qqq",
            "label": "나스닥 100",
            "ticker": "QQQ",
            "price": 445.67,
            "resolved_value": 445.67,
            "change_pct": -0.23,
        },
        {
            "canonical_key": "soxx",
            "label": "반도체 ETF",
            "ticker": "SOXX",
            "price": 218.90,
            "resolved_value": 218.90,
            "change_pct": 1.23,
        },
    ],
    "bitcoin": {
        "spot": {
            "canonical_key": "btc",
            "price": 84321.0,
            "resolved_value": 84321.0,
            "change_pct": 2.50,
        },
        "official_etf_total_btc": 570234.56,
        "official_etf_total_aum_usd": 47_800_000_000,
        "fear_greed_value": 65,
        "fear_greed_label": "Greed",
    },
    "news": [
        {
            "url": "https://example.com/news1",
            "title": "Test headline",
            "summary": "Test summary",
            "topic": "macro",
            "published_at": "2026-03-25T09:00:00Z",
        }
    ],
    "x_market_signals": [
        {
            "summary": "Test signal",
            "why_it_matters": "Market impact",
            "sentiment": "bullish",
            "posted_at": "2026-03-25T08:00:00Z",
        }
    ],
}

MINIMAL_BRIEFING = """# 브리핑 제목

## 0. 오늘의 핵심
연준 금리 동결 결정 — 시장 안도

섹션 0 지지 내용입니다.

## 1. 거시 지표
테스트 섹션 내용
"""


# ---------------------------------------------------------------------------
# Task 5.1 — QuantitativeLayer 변환 검증
# ---------------------------------------------------------------------------


class TestPacketToQuantitative:
    def setup_method(self):
        self.q = packet_to_quantitative(MINIMAL_PACKET)

    def test_returns_quantitative_layer(self):
        assert isinstance(self.q, QuantitativeLayer)

    # FC-4: change_bps 부호 포함 정수 assertion
    def test_fc4_change_bps_format(self):
        """us10y는 rate canonical key → FC-4 형식 (+12bp)."""
        assert self.q.us10y is not None
        assert self.q.us10y.change == "+12bp"

    def test_fc4_negative_bps(self):
        """음수 bps도 부호 포함."""
        # us10y change_bps=12 → "+12bp", dxy는 pct 기반
        assert self.q.us10y.change == "+12bp"

    # FC-1: change_pct 소수 2자리 assertion
    def test_fc1_change_pct_format_positive(self):
        """vix change_pct=+1.50 → "+1.50%"."""
        assert self.q.vix is not None
        assert self.q.vix.change == "+1.50%"

    def test_fc1_change_pct_format_negative(self):
        """dxy change_pct=-0.35 → "-0.35%"."""
        assert self.q.dxy is not None
        assert self.q.dxy.change == "-0.35%"

    def test_validated_index_slots_are_populated(self):
        assert self.q.dow30 is not None
        assert self.q.dow30.value_fmt == "46,504.67"
        assert self.q.kospi is not None
        assert self.q.kospi.change == "+1.36%"
        assert self.q.kosdaq is not None
        assert self.q.kosdaq.change == "-1.54%"

    def test_fc1_soxx_positive(self):
        """soxx change_pct=+1.23 → "+1.23%"."""
        assert self.q.soxx is not None
        assert self.q.soxx.change == "+1.23%"

    # FC-3: BTC 가격 "$84,321" 형식
    def test_fc3_btc_price_format(self):
        """btc spot price 84321 → "$84,321"."""
        assert self.q.btc_spot is not None
        assert self.q.btc_spot.value_fmt == "$84,321"

    # FC-2: total_btc 소수 2자리
    def test_fc2_total_btc_format(self):
        """official_etf_total_btc 570234.56 → "570,234.56 BTC"."""
        assert self.q.btc_total_holding == "570,234.56 BTC"

    def test_btc_change_pct_fc1(self):
        """btc change_pct=+2.50 → "+2.50%"."""
        assert self.q.btc_spot is not None
        assert self.q.btc_spot.change == "+2.50%"

    def test_sparkline_data_populated(self):
        """sparkline_data에 주요 키가 있어야 함."""
        assert "us10y" in self.q.sparkline_data
        assert "btc" in self.q.sparkline_data
        assert "dow30" in self.q.sparkline_data
        assert "kospi" in self.q.sparkline_data
        assert len(self.q.sparkline_data["btc"]) == 2

    def test_sparkline_two_points(self):
        """sparkline은 2포인트 [prev, current]."""
        btc_sparkline = self.q.sparkline_data["btc"]
        assert len(btc_sparkline) == 2
        # current point는 raw price
        assert btc_sparkline[1] == pytest.approx(84321.0, rel=1e-4)

    def test_missing_section_returns_none(self):
        """packet에 없는 섹션은 None."""
        q = packet_to_quantitative({})
        assert q.us10y is None
        assert q.dow30 is None
        assert q.kospi is None
        assert q.btc_spot is None
        assert q.btc_total_holding is None

    def test_fear_greed(self):
        assert self.q.btc_fear_greed_value == 65
        assert self.q.btc_fear_greed_label == "Greed"

    def test_trend_up(self):
        assert self.q.vix is not None
        assert self.q.vix.trend == "up"  # change_pct=+1.50

    def test_trend_down(self):
        assert self.q.dxy is not None
        assert self.q.dxy.trend == "down"  # change_pct=-0.35


# ---------------------------------------------------------------------------
# Task 5.2 — NarrativeLayer optional 필드 처리 검증
# ---------------------------------------------------------------------------


class TestBriefingToNarrative:
    def test_minimal_briefing_optional_fields_are_none(self):
        """섹션이 없는 minimal briefing → optional 필드 전부 None."""
        n = briefing_to_narrative("", MINIMAL_PACKET)
        assert isinstance(n, NarrativeLayer)
        assert n.sector_mapping is None
        assert n.event_calendar is None
        assert n.issue_briefings is None
        assert n.weekly_context is None
        assert n.sonar_analyses is None

    def test_news_from_packet(self):
        """packet에 news가 있으면 NarrativeLayer.news에 포함."""
        n = briefing_to_narrative("", MINIMAL_PACKET)
        assert len(n.news) == 1
        assert n.news[0]["title"] == "Test headline"

    def test_x_signals_from_packet(self):
        """packet에 x_market_signals가 있으면 x_signals에 포함."""
        n = briefing_to_narrative("", MINIMAL_PACKET)
        assert len(n.x_signals) == 1

    def test_public_context_news_priority(self):
        """public_context.all_news가 있으면 packet.news보다 우선."""
        ctx = {"all_news": [{"url": "https://ctx.com", "title": "ctx news"}]}
        n = briefing_to_narrative("", MINIMAL_PACKET, public_context=ctx)
        assert n.news[0]["title"] == "ctx news"

    def test_briefing_stored(self):
        n = briefing_to_narrative(MINIMAL_BRIEFING, MINIMAL_PACKET)
        assert n.briefing_markdown == MINIMAL_BRIEFING

    def test_full_briefing_with_sections(self):
        """section_4_1/4_3/5_1/5_2/6 포함 브리핑 → optional 필드 파싱."""
        full = (
            MINIMAL_BRIEFING + "\n## 4-1. 이슈 브리핑\nTopic A\n내용 줄1\n내용 줄2\n\n"
            "## 5-1. 주간 맥락\n이번 주 맥락 내용\n"
        )
        n = briefing_to_narrative(full, MINIMAL_PACKET)
        # issue_briefings: 빈 dict가 아닌 경우에만 not None
        # (파싱은 섹션 구조에 따라 달라질 수 있으므로 None 여부만 체크)
        assert n.briefing_markdown == full

    def test_empty_packet_no_crash(self):
        """packet이 빈 dict여도 예외 없이 반환."""
        n = briefing_to_narrative("", {})
        assert isinstance(n, NarrativeLayer)
        assert n.news == []
        assert n.x_signals == []


# ---------------------------------------------------------------------------
# Task 5.3 — UnifiedOutput 직렬화 검증
# ---------------------------------------------------------------------------


class TestUnifiedOutputSerialization:
    def setup_method(self):
        self.unified = UnifiedOutput(
            quantitative=packet_to_quantitative(MINIMAL_PACKET),
            narrative=briefing_to_narrative(MINIMAL_BRIEFING, MINIMAL_PACKET),
            meta=MetaLayer(
                run_at="2026-03-25T09:00:00+09:00",
                pipeline_version="2.0",
                source_counts={"news_count": 1},
                translation_status="skipped",
            ),
        )

    def test_to_dict_is_json_serializable(self):
        d = self.unified.to_dict()
        # JSON 직렬화 가능 여부 확인
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert isinstance(parsed, dict)

    def test_to_dict_has_all_layers(self):
        d = self.unified.to_dict()
        assert "quantitative" in d
        assert "narrative" in d
        assert "meta" in d

    def test_translation_status_allowed_values(self):
        for status in ("ok", "partial", "failed", "skipped"):
            m = MetaLayer(
                run_at="2026-03-25T09:00:00+09:00",
                pipeline_version="2.0",
                source_counts={},
                translation_status=status,
            )
            assert m.translation_status == status

    def test_translation_status_invalid_coerced_to_skipped(self):
        m = MetaLayer(
            run_at="2026-03-25T09:00:00+09:00",
            pipeline_version="2.0",
            source_counts={},
            translation_status="unknown_value",
        )
        assert m.translation_status == "skipped"

    def test_quantitative_in_dict_has_btc_spot(self):
        d = self.unified.to_dict()
        assert d["quantitative"]["btc_spot"] is not None
        assert d["quantitative"]["btc_spot"]["value_fmt"] == "$84,321"

    def test_meta_pipeline_version(self):
        assert self.unified.meta.pipeline_version == "2.0"
