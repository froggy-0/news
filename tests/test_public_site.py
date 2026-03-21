from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from morning_brief.config import load_settings
from morning_brief.public_site import build_public_brief, build_public_index, publish_public_brief


def _packet() -> dict:
    return {
        "data_quality": {"status": "degraded", "warnings": ["미국 2년물 금리가 누락되었어요."]},
        "macro": [
            {
                "canonical_key": "us10y",
                "label": "미국 10년물 국채금리",
                "price": 4.25,
                "resolved_value": 4.25,
                "change_bps": 6.0,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            {
                "canonical_key": "dxy",
                "label": "달러 인덱스",
                "price": 100.42,
                "resolved_value": 100.42,
                "change_pct": 0.31,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            {
                "canonical_key": "vix",
                "label": "VIX",
                "price": 17.84,
                "resolved_value": 17.84,
                "change_pct": -2.11,
                "is_previous_value": False,
                "validation_status": "ok",
            },
        ],
        "korea_watch": [
            {
                "canonical_key": "usdkrw",
                "label": "원/달러 환율",
                "price": 1336.2,
                "resolved_value": 1336.2,
                "change_pct": 0.48,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            {
                "canonical_key": "nq_futures",
                "label": "나스닥 선물",
                "price": 20406.5,
                "resolved_value": 20406.5,
                "change_pct": 0.72,
                "is_previous_value": False,
                "validation_status": "ok",
            },
        ],
        "us_indices": [
            {
                "canonical_key": "spy",
                "ticker": "SPY",
                "label": "S&P500",
                "price": 523.83,
                "resolved_value": 523.83,
                "change_pct": 0.61,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            {
                "canonical_key": "qqq",
                "ticker": "QQQ",
                "label": "NASDAQ",
                "price": 448.61,
                "resolved_value": 448.61,
                "change_pct": 0.89,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            {
                "canonical_key": "soxx",
                "ticker": "SOXX",
                "label": "반도체 섹터 (SOXX)",
                "price": 238.43,
                "resolved_value": 238.43,
                "change_pct": 1.27,
                "is_previous_value": False,
                "validation_status": "ok",
            },
        ],
        "tech_stocks": [
            {
                "canonical_key": "nvda",
                "ticker": "NVDA",
                "label": "엔비디아",
                "price": 944.31,
                "resolved_value": 944.31,
                "change_pct": 2.42,
                "is_previous_value": False,
                "validation_status": "ok",
            }
        ],
        "bitcoin": {
            "spot": {
                "canonical_key": "btc",
                "label": "BTC-USD",
                "price": 71282.0,
                "resolved_value": 71282.0,
                "change_pct": -0.16,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            "fear_greed_value": 58,
            "fear_greed_label": "탐욕",
            "official_etf_snapshots": [
                {
                    "ticker": "IBIT",
                    "issuer": "iShares",
                    "source_url": "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust",
                    "total_btc": 573110.2,
                    "aum_usd": 57148000000.0,
                }
            ],
            "official_etf_total_btc": 983240.13,
            "official_etf_total_aum_usd": 98422000000.0,
        },
        "topic_summaries": {
            "macro": {
                "summary_text": "장기 금리 반등이 부담입니다.",
                "market_implication": "장기 금리 반등이 기술주 멀티플에 부담을 줍니다.",
                "key_data_points": ["미국 10년물 4.25%"],
                "notable_stocks": [],
            },
            "us_equity": {
                "summary_text": "지수보다 반도체가 강합니다.",
                "market_implication": "지수 전반보다 반도체와 대형 기술주 중심의 선별 강세가 두드러졌습니다.",
                "key_data_points": ["QQQ +0.89%"],
                "notable_stocks": ["QQQ", "SOXX"],
            },
        },
        "x_market_signals": [
            {
                "headline": "AMD가 차세대 AI 서버 수요 확대를 강조했습니다.",
                "summary": "차세대 AI 서버 수요 확대를 강조했습니다.",
                "why_it_matters": "반도체 투자심리를 지지할 수 있습니다.",
                "sentiment": "bullish",
                "posted_at": "2026-03-21T06:41:00+09:00",
            }
        ],
        "news": [
            {
                "title": "미국 장기 금리 재상승, 기술주 밸류에이션 부담 확대",
                "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                "source": "Reuters",
                "published_at": "2026-03-21T05:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "장기 금리가 다시 올랐습니다.",
                "why_it_matters": "고금리 환경이 성장주 할인율 부담을 키웁니다.",
            }
        ],
    }


def _briefing() -> str:
    return """SOVEREIGN BRIEF

0. 오늘의 핵심
오늘은 관망 국면입니다.
장기 금리가 다시 올라 위험자산의 밸류에이션 부담이 커졌습니다.
오늘 미국 증시 흐름이 코스피에 미치는 영향: 반도체 중심으로 선별 강세가 이어질 수 있습니다.

4-2. 핵심 뉴스 5선
① 미국 장기 금리 재상승, 기술주 밸류에이션 부담 확대 — Reuters
고금리 환경이 성장주 할인율 부담을 키웁니다.
→ 원문 보기 https://www.reuters.com/world/us/fed-keeps-options-open
핵심 한줄: 고금리 환경이 성장주 할인율 부담을 키웁니다.
"""


def test_build_public_index_sorts_dates_descending() -> None:
    index = build_public_index(
        dates=["2026-03-20", "2026-03-21", "2026-03-20"],
        updated_at="2026-03-21T08:00:00+09:00",
    )
    assert index["dates"] == ["2026-03-21", "2026-03-20"]


def test_build_public_brief_matches_frontend_contract_shape() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)

    assert payload["meta"]["date"] == "2026-03-21"
    assert payload["meta"]["dataQuality"] == "degraded"
    assert payload["aiJudgment"]["headline"] == "오늘은 관망 국면입니다."
    assert "오늘의 핵심" in payload["aiJudgment"]["body"]
    symbols = {item["symbol"] for item in payload["marketSnapshot"]["items"]}
    assert {"US10Y", "DXY", "VIX", "KRW", "NQ1!", "SPX", "QQQ", "SOXX", "BTC"} <= symbols
    assert payload["bitcoin"]["fearGreedIndex"]["label"] == "탐욕"
    assert payload["bitcoin"]["etf"]["totalHolding"] == "983,240.13 BTC"
    assert payload["xSignals"][0]["sentiment"] == "bullish"
    assert payload["news"][0]["sourceTier"] == "tier1"
    assert payload["news"][0]["category"] == "macro"


def test_publish_public_brief_writes_local_public_bundle(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    artifacts = publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    brief_path = settings.output_dir / "public" / artifacts.brief_relative_path
    index_path = settings.output_dir / "public" / "index.json"

    assert brief_path.exists()
    assert index_path.exists()

    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_payload["dates"] == ["2026-03-21"]
