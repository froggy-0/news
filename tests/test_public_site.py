from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError

import morning_brief.public_site as public_site
from morning_brief.config import load_settings
from morning_brief.observability import PipelineObserver
from morning_brief.public_site import build_public_brief, build_public_index, publish_public_brief
from morning_brief.unified_output import (
    MetaLayer,
    UnifiedOutput,
    briefing_to_narrative,
    packet_to_quantitative,
)


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
        "korea_indices": [
            {
                "canonical_key": "kospi",
                "ticker": "0001",
                "label": "코스피",
                "price": 5450.33,
                "resolved_value": 5450.33,
                "change_pct": 1.36,
                "is_previous_value": False,
                "validation_status": "ok",
            },
            {
                "canonical_key": "kosdaq",
                "ticker": "1001",
                "label": "코스닥",
                "price": 1047.37,
                "resolved_value": 1047.37,
                "change_pct": -1.54,
                "is_previous_value": False,
                "validation_status": "ok",
            },
        ],
        "validated_indices": [
            {
                "canonical_key": "dow30",
                "ticker": ".DJI",
                "label": "다우30",
                "price": 46504.67,
                "resolved_value": 46504.67,
                "change_pct": -0.13,
                "is_previous_value": False,
                "validation_status": "ok",
            }
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
    assert payload["meta"]["displayHeadline"] == "오늘은 관망 국면입니다."
    assert payload["meta"]["translationStatus"] == "ok"
    assert (
        payload["aiJudgment"]["summaryLead"]
        == "장기 금리가 다시 올라 위험자산의 밸류에이션 부담이 커졌습니다."
    )
    assert (
        payload["aiJudgment"]["summarySupport"]
        == "오늘 미국 증시 흐름이 코스피에 미치는 영향: 반도체 중심으로 선별 강세가 이어질 수 있습니다."
    )
    assert "오늘의 핵심" in payload["aiJudgment"]["body"]
    assert "4-2. 핵심 뉴스 5선" not in payload["aiJudgment"]["body"]
    symbols = {item["symbol"] for item in payload["marketSnapshot"]["items"]}
    assert {"US10Y", "DXY", "VIX", "BTC"} <= symbols
    assert {"KRW", "NQ1!", "DJI", "KOSPI", "KOSDAQ", "SPX", "QQQ", "SOXX"}.isdisjoint(symbols)
    assert payload["techStocks"] == []
    crypto_symbols = {item["symbol"] for item in payload["cryptoIndicators"]}
    assert {"BTC", "F&G", "ETF BTC", "ETF AUM", "VIX", "DXY"} <= crypto_symbols
    assert payload["bitcoin"]["fearGreedIndex"]["label"] == "탐욕"
    assert payload["bitcoin"]["etf"]["totalHolding"] == "983,240.13 BTC"
    assert payload["featuredXSignals"][0]["sentiment"] == "bullish"
    assert payload["featuredXSignals"][0]["rawContent"] is None
    assert payload["allNews"][0]["sourceTier"] == "tier1"
    assert payload["allNews"][0]["category"] == "macro"
    assert payload["allNews"][0]["summaryKo"] == "장기 금리가 다시 올랐습니다."
    assert payload["allNews"][0]["interpretation"] == "고금리 환경이 성장주 할인율 부담을 키웁니다."
    assert payload["allNews"][0]["rawTitle"] is None
    assert payload["meta"]["sourceCounts"]["newsAll"] == 1
    assert payload["meta"]["sourceCounts"]["xSignalAll"] == 1


def test_build_public_brief_skips_source_reference_when_deriving_headline() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(
        packet=_packet(),
        briefing="""SOVEREIGN BRIEF

참고 출처 - https://www.reuters.com/world/us/fed-keeps-options-open

오늘 시장은 지정학 리스크와 금리 부담이 동시에 작용하는 국면입니다.
반도체 중심의 선별 대응이 유효합니다.
""",
        run_at=run_at,
    )

    assert (
        payload["meta"]["displayHeadline"]
        == "오늘 시장은 지정학 리스크와 금리 부담이 동시에 작용하는 국면입니다."
    )
    assert "https://" not in payload["meta"]["displayHeadline"]


def test_build_public_brief_prefers_public_context_for_full_lists() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "all_news": [
            {
                "title": "첫 번째 공개 뉴스",
                "url": "https://example.com/news-1",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "첫 번째 공개 뉴스 요약",
                "why_it_matters": "첫 번째 공개 뉴스 해석",
            },
            {
                "title": "두 번째 공개 뉴스",
                "url": "https://example.com/news-2",
                "source": "Bloomberg",
                "published_at": "2026-03-21T07:40:00+09:00",
                "topic": "us_equity",
                "source_tier": 1,
                "summary": "두 번째 공개 뉴스 요약",
                "why_it_matters": "두 번째 공개 뉴스 해석",
            },
        ],
        "all_x_signals": [
            {
                "headline": "첫 번째 공개 시그널",
                "summary": "첫 번째 공개 시그널 요약",
                "why_it_matters": "첫 번째 공개 시그널 영향",
                "sentiment": "bullish",
                "posted_at": "2026-03-21T07:35:00+09:00",
            },
            {
                "headline": "두 번째 공개 시그널",
                "summary": "두 번째 공개 시그널 요약",
                "why_it_matters": "두 번째 공개 시그널 영향",
                "sentiment": "neutral",
                "posted_at": "2026-03-21T07:25:00+09:00",
            },
        ],
        "source_counts": {
            "newsCandidates": 14,
            "newsRanked": 12,
            "newsFeatured": 2,
            "newsAll": 2,
            "xSignalCandidates": 9,
            "xSignalRanked": 2,
            "xSignalFeatured": 2,
            "xSignalAll": 2,
        },
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    assert len(payload["allNews"]) == 2
    assert payload["allNews"][1]["title"] == "두 번째 공개 뉴스"
    assert len(payload["allXSignals"]) == 2
    assert payload["meta"]["sourceCounts"]["newsCandidates"] == 14
    assert payload["meta"]["sourceCounts"]["xSignalCandidates"] == 9


def test_build_public_brief_drops_placeholder_featured_news_from_public_context() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "all_news": [
            {
                "title": "국채 금리 방향성 점검",
                "url": "https://www.reuters.com/world/us/treasury-yields-check",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "해당 없음",
                "why_it_matters": "해당 없음",
            }
        ],
        "all_x_signals": [],
        "source_counts": {
            "newsCandidates": 1,
            "newsRanked": 1,
            "newsFeatured": 1,
            "newsAll": 1,
            "xSignalCandidates": 0,
            "xSignalRanked": 0,
            "xSignalFeatured": 0,
            "xSignalAll": 0,
        },
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    assert payload["allNews"] == []
    assert payload["featuredNews"] == []


def test_build_public_brief_prefers_unified_news_over_polluted_public_context() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    filtered_context = {
        "all_news": [
            {
                "title": "미국 장기 금리 반등으로 성장주 압박",
                "url": "https://www.reuters.com/world/us/yields-pressure-growth",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "장기 금리가 다시 오르며 기술주 부담이 커졌습니다.",
                "why_it_matters": "고금리 환경이 성장주 할인율 부담을 키웁니다.",
            }
        ],
        "all_x_signals": [
            {
                "headline": "ETF fee war chatter",
                "summary": "ETF fee war chatter",
                "why_it_matters": "단기 심리에 우호적일 수 있습니다.",
                "sentiment": "bullish",
                "posted_at": "2026-03-21T07:35:00+09:00",
            }
        ],
        "source_counts": {
            "newsCandidates": 1,
            "newsRanked": 1,
            "newsFeatured": 1,
            "newsAll": 1,
            "xSignalCandidates": 1,
            "xSignalRanked": 1,
            "xSignalFeatured": 1,
            "xSignalAll": 1,
        },
    }
    polluted_context = {
        "all_news": [
            {
                "title": "ETF fee war chatter",
                "url": "https://x.com/EricBalchunas/status/123",
                "source": "@EricBalchunas",
                "published_at": "2026-03-21T07:49:00+09:00",
                "topic": "bitcoin",
                "source_tier": 1,
                "summary": "ETF fee war chatter",
                "why_it_matters": "ETF fee war chatter",
            }
        ],
        "all_x_signals": [],
        "source_counts": filtered_context["source_counts"],
    }
    unified = UnifiedOutput(
        quantitative=packet_to_quantitative(_packet()),
        narrative=briefing_to_narrative(_briefing(), _packet(), filtered_context),
        meta=MetaLayer(
            run_at=run_at.isoformat(),
            pipeline_version="2.0",
            source_counts=filtered_context["source_counts"],
            translation_status="ok",
        ),
    )

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=polluted_context,
        unified=unified,
    )

    assert [item["source"] for item in payload["allNews"]] == ["Reuters"]
    assert payload["featuredNews"][0]["source"] == "Reuters"


def test_build_public_brief_hides_sparse_market_snapshot() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    packet = _packet()
    packet["macro"] = []
    packet["korea_watch"] = []
    packet["korea_indices"] = []
    packet["validated_indices"] = []
    packet["us_indices"] = []
    packet["bitcoin"]["spot"] = {}

    payload = build_public_brief(
        packet=packet,
        briefing=_briefing(),
        run_at=run_at,
    )

    assert payload["marketSnapshot"]["items"] == []


def test_build_public_brief_translates_selected_public_texts(monkeypatch, tmp_path) -> None:
    class FakeOpenAI:
        def __init__(self, *, api_key: str):
            self.api_key = api_key
            self.responses = self

        def create(self, **kwargs):
            payload = json.loads(kwargs["input"])
            translated = [
                {"id": item["id"], "translated": f"번역 {index}"}
                for index, item in enumerate(payload["items"], start=1)
            ]
            return SimpleNamespace(
                output_text=json.dumps({"items": translated}, ensure_ascii=False),
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=20,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=0),
                ),
            )

    english_packet = _packet()
    english_packet["topic_summaries"]["macro"]["market_implication"] = "Rates remain elevated."
    english_packet["x_market_signals"] = [
        {
            "headline": "AI server demand is accelerating.",
            "summary": "AI server demand is accelerating.",
            "why_it_matters": "It can support chip sentiment.",
            "sentiment": "bullish",
            "posted_at": "2026-03-21T06:41:00+09:00",
        }
    ]
    english_packet["news"] = [
        {
            "title": "Tech valuations face pressure as yields rise",
            "url": "https://www.reuters.com/world/us/tech-valuations-face-pressure",
            "source": "Reuters",
            "published_at": "2026-03-21T05:50:00+09:00",
            "topic": "macro",
            "source_tier": 1,
            "summary": "Long-end yields moved higher.",
            "why_it_matters": "Growth stocks face a higher discount-rate burden.",
        }
    ]

    monkeypatch.setattr("morning_brief.public_site.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    payload = build_public_brief(
        packet=english_packet,
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    assert payload["meta"]["translationStatus"] == "ok"
    assert payload["topicSummaries"][0]["summary"].startswith("번역")
    assert payload["featuredNews"][0]["title"].startswith("번역")
    assert payload["featuredNews"][0]["rawTitle"] == "Tech valuations face pressure as yields rise"
    assert payload["allNews"][0]["title"].startswith("번역")
    assert payload["allNews"][0]["rawTitle"] == "Tech valuations face pressure as yields rise"
    assert payload["featuredXSignals"][0]["content"].startswith("번역")
    assert payload["featuredXSignals"][0]["rawContent"] == "AI server demand is accelerating."
    assert payload["allXSignals"][0]["content"].startswith("번역")
    assert payload["allXSignals"][0]["rawContent"] == "AI server demand is accelerating."


def test_build_public_brief_translation_batches_recover_from_partial_invalid_json(
    monkeypatch, tmp_path
) -> None:
    class FakeOpenAI:
        calls = 0

        def __init__(self, *, api_key: str):
            self.api_key = api_key
            self.responses = self

        def create(self, **kwargs):
            FakeOpenAI.calls += 1
            if FakeOpenAI.calls == 1:
                return SimpleNamespace(
                    output_text='{"items":[{"id":"broken"',
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        input_tokens_details=SimpleNamespace(cached_tokens=0),
                        output_tokens_details=SimpleNamespace(reasoning_tokens=0),
                    ),
                )

            payload = json.loads(kwargs["input"])
            translated = [
                {"id": item["id"], "translated": f"번역 {index}"}
                for index, item in enumerate(payload["items"], start=1)
            ]
            return SimpleNamespace(
                output_text=json.dumps({"items": translated}, ensure_ascii=False),
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=20,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=0),
                ),
            )

    english_packet = _packet()
    english_packet["topic_summaries"]["macro"]["market_implication"] = "Rates remain elevated."
    english_packet["news"] = [
        {
            "title": f"English title {index}",
            "url": (
                f"https://www.reuters.com/world/us/english-news-{index}"
                if index == 0
                else f"https://www.cnbc.com/2026/03/21/english-news-{index}.html"
            ),
            "source": "Reuters" if index == 0 else "CNBC",
            "published_at": "2026-03-21T05:50:00+09:00",
            "topic": "macro",
            "source_tier": 1,
            "summary": f"English summary {index}",
            "why_it_matters": f"English why it matters {index}",
        }
        for index in range(2)
    ]
    english_packet["x_market_signals"] = [
        {
            "headline": f"English signal headline {index}",
            "summary": f"English signal summary {index}",
            "why_it_matters": f"English signal impact {index}",
            "sentiment": "bearish",
            "posted_at": "2026-03-21T06:41:00+09:00",
        }
        for index in range(2)
    ]

    monkeypatch.setattr("morning_brief.public_site.OpenAI", FakeOpenAI)
    monkeypatch.setattr(public_site, "_PUBLIC_TRANSLATION_BATCH_ITEMS", 1)
    monkeypatch.setattr(public_site, "_PUBLIC_TRANSLATION_BATCH_CHARS", 200)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    payload = build_public_brief(
        packet=english_packet,
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    assert FakeOpenAI.calls > 1
    assert payload["meta"]["translationStatus"] == "partial"
    assert any(str(item["title"]).startswith("번역") for item in payload["featuredNews"])
    assert any(str(item["title"]).startswith("번역") for item in payload["allNews"])


def test_publish_public_brief_writes_local_public_bundle(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.delenv("R2_PUBLIC_BUCKET", raising=False)
    monkeypatch.delenv("R2_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
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


def test_publish_public_brief_r2_signature_failure_falls_back_to_local(
    monkeypatch, tmp_path
) -> None:
    class FakeR2Client:
        def put_json(self, key: str, payload: dict) -> None:
            raise ClientError(
                {
                    "Error": {
                        "Code": "SignatureDoesNotMatch",
                        "Message": "The request signature we calculated does not match",
                    }
                },
                "PutObject",
            )

        def list_dates(self) -> list[str]:
            raise AssertionError("list_dates should not be called after upload failure")

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(public_site, "_public_r2_client", lambda settings: FakeR2Client())
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path / "observability")
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    artifacts = publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
        observer=observer,
    )

    brief_path = settings.output_dir / "public" / artifacts.brief_relative_path
    index_path = settings.output_dir / "public" / "index.json"

    assert brief_path.exists()
    assert index_path.exists()
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_payload["dates"] == ["2026-03-21"]

    failure_event = next(
        event for event in observer.events if event["event"] == "public_brief_upload_failed"
    )
    assert failure_event["reason"].startswith("R2 PutObject 서명이 맞지 않습니다.")
    assert failure_event["error_code"] == "SignatureDoesNotMatch"
    assert failure_event["endpoint_host"] == "example.r2.cloudflarestorage.com"

    published_event = next(
        event for event in observer.events if event["event"] == "public_brief_published"
    )
    assert published_event["uploaded"] is False


def test_publish_public_brief_invalid_r2_endpoint_falls_back_to_local(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://example.r2.cloudflarestorage.com/test-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path / "observability")
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    artifacts = publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
        observer=observer,
    )

    index_path = settings.output_dir / "public" / "index.json"
    assert (settings.output_dir / "public" / artifacts.brief_relative_path).exists()
    assert index_path.exists()

    failure_event = next(
        event for event in observer.events if event["event"] == "public_brief_upload_failed"
    )
    assert (
        failure_event["reason"]
        == "R2_S3_ENDPOINT must use the account-level S3 endpoint only, without bucket/path/query."
    )
    assert failure_event["stage"] == "client_init"

    published_event = next(
        event for event in observer.events if event["event"] == "public_brief_published"
    )
    assert published_event["uploaded"] is False


def test_build_public_brief_uses_source_text_instead_of_generic_copy() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    packet = _packet()
    packet["news"] = [
        {
            "title": "English-only title from source",
            "url": "https://example.com/news-raw",
            "source": "Example",
            "published_at": "2026-03-21T07:50:00+09:00",
            "topic": "macro",
            "source_tier": 1,
            "summary": "",
            "why_it_matters": "",
        }
    ]
    packet["x_market_signals"] = [
        {
            "headline": "English-only official signal",
            "summary": "",
            "why_it_matters": "",
            "sentiment": "neutral",
            "posted_at": "2026-03-21T06:41:00+09:00",
        }
    ]

    payload = build_public_brief(
        packet=packet,
        briefing="""SOVEREIGN BRIEF

연준 점도표와 중동 변수로 장중 변동성이 커졌습니다.
""",
        run_at=run_at,
    )

    assert (
        payload["aiJudgment"]["headline"] == "연준 점도표와 중동 변수로 장중 변동성이 커졌습니다."
    )
    assert (
        payload["aiJudgment"]["summaryLead"]
        == "연준 점도표와 중동 변수로 장중 변동성이 커졌습니다."
    )
    assert payload["featuredNews"] == []
    assert payload["allNews"] == []
    assert payload["featuredXSignals"] is None
    assert payload["allXSignals"][0]["content"] == "English-only official signal"


def test_build_public_brief_uses_generated_public_news_analysis_fields() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "all_news": [
            {
                "title": "미국 장기 금리 반등으로 성장주 압박",
                "url": "https://www.reuters.com/world/us/yields-pressure-growth",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "Long-end yields rose.",
                "why_it_matters": "Growth stocks face pressure.",
                "summary_ko": "장기 금리가 오르면서 성장주 압박이 커졌습니다.",
                "interpretation_ko": "고금리 부담이 기술주 선호를 약하게 만들 수 있습니다.",
            }
        ],
        "all_x_signals": [],
        "source_counts": {
            "newsCandidates": 1,
            "newsRanked": 1,
            "newsFeatured": 1,
            "newsAll": 1,
            "xSignalCandidates": 0,
            "xSignalRanked": 0,
            "xSignalFeatured": 0,
            "xSignalAll": 0,
        },
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    assert payload["allNews"][0]["summaryKo"] == "장기 금리가 오르면서 성장주 압박이 커졌습니다."
    assert (
        payload["allNews"][0]["interpretation"]
        == "고금리 부담이 기술주 선호를 약하게 만들 수 있습니다."
    )


def test_build_public_brief_filters_all_news_when_summary_or_interpretation_is_missing() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "all_news": [
            {
                "title": "미국 장기 금리 반등으로 성장주 압박",
                "url": "https://www.reuters.com/world/us/yields-pressure-growth",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "Long-end yields rose.",
                "why_it_matters": "Growth stocks face pressure.",
                "summary_ko": "장기 금리가 오르면서 성장주 압박이 커졌습니다.",
                "interpretation_ko": "해당 없음",
            }
        ],
        "all_x_signals": [],
        "source_counts": {
            "newsCandidates": 1,
            "newsRanked": 1,
            "newsFeatured": 1,
            "newsAll": 1,
            "xSignalCandidates": 0,
            "xSignalRanked": 0,
            "xSignalFeatured": 0,
            "xSignalAll": 0,
        },
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    assert payload["allNews"] == []
    assert payload["featuredNews"] == []


def test_build_public_brief_skips_translation_when_only_single_low_value_topic_summary_remains(
    monkeypatch, tmp_path
) -> None:
    class FakeOpenAI:
        called = False

        def __init__(self, *, api_key: str):
            self.api_key = api_key
            self.responses = self

        def create(self, **kwargs):
            FakeOpenAI.called = True
            return SimpleNamespace(output_text='{"items":[]}', usage=None)

    packet = _packet()
    packet["topic_summaries"] = {
        "macro": {
            "summary_text": "Long-end yields stayed elevated overnight.",
            "market_implication": "",
            "key_data_points": [],
            "notable_stocks": [],
        }
    }
    packet["news"] = []
    packet["x_market_signals"] = []
    briefing = """SOVEREIGN BRIEF

2026-03-21 발행본
장기 금리 부담이 이어졌습니다.
"""

    monkeypatch.setattr("morning_brief.public_site.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    payload = build_public_brief(
        packet=packet,
        briefing=briefing,
        run_at=run_at,
        settings=settings,
    )

    assert FakeOpenAI.called is False
    assert payload["meta"]["translationStatus"] == "ok"
    assert payload["topicSummaries"][0]["summary"] == "Long-end yields stayed elevated overnight."


# ── Phase A: 영문 원본 보존 테스트 ──────────────────────────────


def test_build_public_brief_preserves_raw_summary_and_raw_interpretation_for_english() -> None:
    """영문 summary/why_it_matters가 rawSummary/rawInterpretation으로 보존된다."""
    packet = _packet()
    packet["news"] = [
        {
            "title": "미국 국채 금리 재하락",
            "url": "https://www.reuters.com/markets/rates",
            "source": "Reuters",
            "published_at": "2026-03-21T05:50:00+09:00",
            "topic": "macro",
            "source_tier": 1,
            "summary": "Bond yields fell as investors sought safety.",
            "summary_ko": "채권 금리가 안전자산 선호 속 하락했습니다.",
            "why_it_matters": "Lower yields could ease pressure on growth stocks.",
            "interpretation_ko": "금리 하락이 성장주 부담을 완화할 수 있습니다.",
        }
    ]
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=packet, briefing=_briefing(), run_at=run_at)

    news = payload["allNews"][0]
    assert news["rawTitle"] is None  # 한국어 제목이므로 rawTitle은 None
    assert news["rawSummary"] == "Bond yields fell as investors sought safety."
    assert news["rawInterpretation"] == "Lower yields could ease pressure on growth stocks."


def test_build_public_brief_sets_raw_fields_null_for_korean() -> None:
    """한국어 summary/why_it_matters면 rawSummary/rawInterpretation은 null."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)

    news = payload["allNews"][0]
    assert news["rawTitle"] is None  # 기존 — 한국어 제목이므로 None
    assert news["rawSummary"] is None
    assert news["rawInterpretation"] is None


def test_build_public_brief_topic_summary_raw_summary_english() -> None:
    """영문 토픽 요약이 rawSummary로 보존된다."""
    packet = _packet()
    packet["topic_summaries"] = {
        "macro": {
            "summary_text": "Long-end yields stayed elevated.",
            "market_implication": "Rising rates pressure tech multiples.",
            "key_data_points": ["US10Y 4.25%"],
            "notable_stocks": [],
        },
    }
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=packet, briefing=_briefing(), run_at=run_at)

    topic = payload["topicSummaries"][0]
    assert topic["rawSummary"] == "Rising rates pressure tech multiples."


def test_build_public_brief_topic_summary_raw_summary_null_for_korean() -> None:
    """한국어 토픽 요약이면 rawSummary는 null."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)

    topic = payload["topicSummaries"][0]
    assert topic["rawSummary"] is None


def test_build_public_brief_topic_summaries_do_not_gain_sentiment_fields() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)

    topic = payload["topicSummaries"][0]
    assert "sentimentScore" not in topic
    assert "sentimentConfidence" not in topic
    assert "sentimentLabel" not in topic


# ── Phase B: sentiment 출력 / 집계 테스트 ──────────────────────


def test_build_public_brief_news_sentiment_fields_present() -> None:
    """뉴스 출력에 sentimentScore/Confidence/Label이 존재한다."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)
    news = payload["allNews"][0]
    assert "sentimentScore" in news
    assert "sentimentConfidence" in news
    assert "sentimentLabel" in news
    # score가 None이면 label도 None
    assert news["sentimentScore"] is None
    assert news["sentimentLabel"] is None


def test_build_public_brief_xsignal_sentiment_fields_present() -> None:
    """X시그널 출력에 감성 필드 존재 + 기존 sentiment 필드 유지."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)
    sig = payload["featuredXSignals"][0]
    assert sig["sentiment"] == "bullish"  # 기존 Grok 라벨 유지
    assert "sentimentScore" in sig
    assert "sentimentLabel" in sig


def test_build_public_brief_meta_sentiment_status() -> None:
    """meta.sentimentStatus 및 signalSentimentStatus 필드가 존재한다."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = build_public_brief(packet=_packet(), briefing=_briefing(), run_at=run_at)
    assert payload["meta"]["sentimentStatus"] == "skipped"
    assert payload["meta"]["signalSentimentStatus"] == "skipped"
    assert "newsSentiment" in payload["meta"]
    assert "signalSentiment" in payload["meta"]
    assert "sentimentByCategory" in payload["meta"]


def test_build_public_brief_uses_public_context_sentiment_status_and_count() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "sentiment_status": "ok",
        "all_news": [
            {
                "title": "첫 번째 공개 뉴스",
                "url": "https://example.com/news-1",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "첫 번째 공개 뉴스 요약",
                "why_it_matters": "첫 번째 공개 뉴스 해석",
                "sentiment_score": 0.31,
                "sentiment_confidence": 0.87,
            },
            {
                "title": "두 번째 공개 뉴스",
                "url": "https://example.com/news-2",
                "source": "Bloomberg",
                "published_at": "2026-03-21T07:40:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "두 번째 공개 뉴스 요약",
                "why_it_matters": "두 번째 공개 뉴스 해석",
                "sentiment_score": -0.28,
                "sentiment_confidence": 0.91,
            },
        ],
        "all_x_signals": [],
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    assert payload["meta"]["sentimentStatus"] == "ok"
    assert payload["meta"]["signalSentimentStatus"] == "skipped"
    assert payload["meta"]["newsSentiment"]["count"] == 2
    assert payload["allNews"][0]["sentimentScore"] == 0.31
    assert payload["allNews"][1]["sentimentScore"] == -0.28


def test_build_public_brief_news_sentiment_includes_unfiltered_articles() -> None:
    """한국어 번역 없어 display에서 제외된 기사도 sentimentScore가 있으면 newsSentiment에 집계된다."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "sentiment_status": "ok",
        "all_news": [
            {
                "title": "번역된 뉴스",
                "url": "https://example.com/news-1",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "요약",
                "why_it_matters": "해석",
                "sentiment_score": 0.5,
                "sentiment_confidence": 0.9,
            },
            {
                # summaryKo/interpretation 없음 → display_news에서 제외되지만 all_news에 존재
                "title": "번역 미완성 뉴스",
                "url": "https://example.com/news-2",
                "source": "Bloomberg",
                "published_at": "2026-03-21T07:40:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "",
                "why_it_matters": "",
                "sentiment_score": -0.4,
                "sentiment_confidence": 0.85,
            },
        ],
        "all_x_signals": [],
    }
    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )
    # display_news는 1개(번역 있는 것만), all_news는 2개 → newsSentiment.count == 2
    assert payload["meta"]["newsSentiment"]["count"] == 2
    # allNews에는 display 통과한 1개만 노출
    assert len(payload["allNews"]) == 1


def test_build_public_brief_signal_sentiment_status_independent() -> None:
    """sentimentStatus(뉴스)와 signalSentimentStatus(시그널)는 독립적으로 반영된다."""
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "sentiment_status": "ok",
        "signal_sentiment_status": "failed",
        "all_news": [],
        "all_x_signals": [],
    }
    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )
    # 뉴스 상태는 ok 유지 — 다운스트림 r2_sentiment 계약 보호
    assert payload["meta"]["sentimentStatus"] == "ok"
    # 시그널 실패는 별도 필드로 명시
    assert payload["meta"]["signalSentimentStatus"] == "failed"


def test_build_public_brief_persists_public_x_signal_sentiment() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "all_news": [],
        "all_x_signals": [
            {
                "headline": "첫 번째 공개 시그널",
                "summary": "첫 번째 공개 시그널 요약",
                "why_it_matters": "첫 번째 공개 시그널 영향",
                "sentiment": "bullish",
                "sentiment_score": 0.44,
                "sentiment_confidence": 0.92,
                "posted_at": "2026-03-21T07:35:00+09:00",
            },
            {
                "headline": "두 번째 공개 시그널",
                "summary": "두 번째 공개 시그널 요약",
                "why_it_matters": "두 번째 공개 시그널 영향",
                "sentiment": "neutral",
                "sentiment_score": -0.12,
                "sentiment_confidence": 0.81,
                "posted_at": "2026-03-21T07:25:00+09:00",
            },
        ],
        "featured_x_signals": [
            {
                "headline": "첫 번째 공개 시그널",
                "summary": "첫 번째 공개 시그널 요약",
                "why_it_matters": "첫 번째 공개 시그널 영향",
                "sentiment": "bullish",
                "sentiment_score": 0.44,
                "sentiment_confidence": 0.92,
                "posted_at": "2026-03-21T07:35:00+09:00",
            }
        ],
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    assert payload["meta"]["signalSentiment"]["count"] == 2
    assert payload["allXSignals"][0]["sentimentScore"] == 0.44
    assert payload["allXSignals"][0]["sentimentConfidence"] == 0.92
    assert payload["featuredXSignals"][0]["sentimentScore"] == 0.44
    assert payload["xSignals"][0]["sentimentScore"] == 0.44


def test_build_public_brief_camelcase_sentiment_mirrors_snake_case_values() -> None:
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    public_context = {
        "all_news": [
            {
                "title": "공개 뉴스",
                "url": "https://example.com/news-1",
                "source": "Reuters",
                "published_at": "2026-03-21T07:50:00+09:00",
                "topic": "macro",
                "source_tier": 1,
                "summary": "공개 뉴스 요약",
                "why_it_matters": "공개 뉴스 해석",
                "sentiment_score": 0.31,
                "sentiment_confidence": 0.87,
            }
        ],
        "all_x_signals": [
            {
                "headline": "공개 시그널",
                "summary": "공개 시그널 요약",
                "why_it_matters": "공개 시그널 영향",
                "sentiment": "bullish",
                "sentiment_score": 0.44,
                "sentiment_confidence": 0.92,
                "posted_at": "2026-03-21T07:35:00+09:00",
            }
        ],
        "featured_x_signals": [
            {
                "headline": "공개 시그널",
                "summary": "공개 시그널 요약",
                "why_it_matters": "공개 시그널 영향",
                "sentiment": "bullish",
                "sentiment_score": 0.44,
                "sentiment_confidence": 0.92,
                "posted_at": "2026-03-21T07:35:00+09:00",
            }
        ],
    }

    payload = build_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        public_context=public_context,
    )

    news = payload["allNews"][0]
    signal = payload["allXSignals"][0]
    featured_signal = payload["featuredXSignals"][0]

    assert news["sentiment_score"] == news["sentimentScore"] == 0.31
    assert news["sentiment_confidence"] == news["sentimentConfidence"] == 0.87
    assert news["sentimentLabel"] == "bullish"
    assert signal["sentiment_score"] == signal["sentimentScore"] == 0.44
    assert signal["sentiment_confidence"] == signal["sentimentConfidence"] == 0.92
    assert signal["sentimentLabel"] == "bullish"
    assert featured_signal["sentiment_score"] == featured_signal["sentimentScore"] == 0.44
    assert featured_signal["sentiment_confidence"] == featured_signal["sentimentConfidence"] == 0.92
    assert featured_signal["sentimentLabel"] == "bullish"


def test_compute_sentiment_aggregate_normal() -> None:
    """정상 케이스: 분리 집계 검증."""
    from morning_brief.public_site import _compute_sentiment_aggregate

    items = [
        {"sentimentScore": 0.5, "sentimentLabel": "bullish"},
        {"sentimentScore": -0.4, "sentimentLabel": "bearish"},
        {"sentimentScore": 0.1, "sentimentLabel": "neutral"},
        {"sentimentScore": 0.8, "sentimentLabel": "bullish"},
        {"sentimentScore": -0.2, "sentimentLabel": "neutral"},
    ]
    agg = _compute_sentiment_aggregate(items)
    assert agg["count"] == 5
    assert agg["mean"] is not None
    assert agg["median"] is not None
    assert agg["std"] is not None
    assert agg["bullishRatio"] == round(2 / 5, 4)
    assert agg["bearishRatio"] == round(1 / 5, 4)


def test_compute_sentiment_aggregate_with_nulls() -> None:
    """null 포함: None 항목은 제외."""
    from morning_brief.public_site import _compute_sentiment_aggregate

    items = [
        {"sentimentScore": 0.5, "sentimentLabel": "bullish"},
        {"sentimentScore": None, "sentimentLabel": None},
        {"sentimentScore": -0.3, "sentimentLabel": "bearish"},
    ]
    agg = _compute_sentiment_aggregate(items)
    assert agg["count"] == 2


def test_compute_sentiment_aggregate_all_null() -> None:
    """전체 null: 모든 필드 null, count=0."""
    from morning_brief.public_site import _compute_sentiment_aggregate

    items = [{"sentimentScore": None}, {"sentimentScore": None}]
    agg = _compute_sentiment_aggregate(items)
    assert agg["count"] == 0
    assert agg["mean"] is None
    assert agg["median"] is None


def test_compute_sentiment_by_category_filters_small() -> None:
    """카테고리별 집계: 2건 미만은 제외."""
    from morning_brief.public_site import _compute_sentiment_by_category

    items = [
        {"category": "macro", "sentimentScore": 0.5},
        {"category": "macro", "sentimentScore": -0.1},
        {"category": "macro", "sentimentScore": 0.3},
        {"category": "bigtech", "sentimentScore": 0.2},  # 1건 → 제외
    ]
    result = _compute_sentiment_by_category(items)
    assert result is not None
    assert "macro" in result
    assert result["macro"]["count"] == 3
    assert "bigtech" not in result


# ── Phase C: dual-write 테스트 ──────────────────────────────


def test_publish_public_brief_dual_writes_curated_and_analytics(monkeypatch, tmp_path) -> None:
    """curated + analytics dual-write가 같은 날짜 기준으로 생성되는지 검증한다."""
    written_keys: list[str] = []

    class FakeR2Client:
        def put_json(self, key: str, payload: dict) -> None:
            written_keys.append(key)

        def list_dates(self) -> list[str]:
            return ["2026-03-21"]

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://test.endpoint")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(public_site, "_public_r2_client", lambda settings: FakeR2Client())
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    assert "briefs/2026-03-21.json" in written_keys
    assert "curated/btc/2026-03-21.json" in written_keys
    assert "analytics/btc/2026-03-21.json" in written_keys


def test_publish_public_brief_analytics_payload_matches_contract(monkeypatch, tmp_path) -> None:
    """analytics payload가 계약 필드만 포함하는지 검증한다."""
    from morning_brief.data.storage.analytics_contract import validate_analytics_sentiment_payload

    captured_payloads: dict[str, dict] = {}

    class FakeR2Client:
        def put_json(self, key: str, payload: dict) -> None:
            captured_payloads[key] = payload

        def list_dates(self) -> list[str]:
            return ["2026-03-21"]

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://test.endpoint")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(public_site, "_public_r2_client", lambda settings: FakeR2Client())
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    analytics = captured_payloads["analytics/btc/2026-03-21.json"]
    validation = validate_analytics_sentiment_payload(analytics)
    assert validation["valid"] is True
    assert analytics["_backfill"] is False  # D-3: 라이브 파이프라인은 _backfill=False (명시)
    assert analytics["symbol"] == "btc"
    assert analytics["date"] == "2026-03-21"
    assert set(analytics["newsSentiment"].keys()) == {"mean", "std", "count"}
    # 실시간 파이프라인은 build_public_news_sentiment_text (title+summary+interpretation)
    assert analytics["textSchemaVersion"] == "title_summary_whyitmatters"


def test_publish_public_brief_curated_preserves_full_payload(monkeypatch, tmp_path) -> None:
    """curated payload는 기존 전시 JSON 스키마를 유지한다."""
    captured_payloads: dict[str, dict] = {}

    class FakeR2Client:
        def put_json(self, key: str, payload: dict) -> None:
            captured_payloads[key] = payload

        def list_dates(self) -> list[str]:
            return ["2026-03-21"]

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://test.endpoint")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(public_site, "_public_r2_client", lambda settings: FakeR2Client())
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    curated = captured_payloads["curated/btc/2026-03-21.json"]
    legacy = captured_payloads["briefs/2026-03-21.json"]
    assert curated == legacy
    assert "meta" in curated
    assert "aiJudgment" in curated
    assert "marketSnapshot" in curated


def test_publish_public_brief_legacy_briefs_still_written(monkeypatch, tmp_path) -> None:
    """migration 기간 동안 legacy briefs/{date}.json 저장이 유지된다."""
    written_keys: list[str] = []

    class FakeR2Client:
        def put_json(self, key: str, payload: dict) -> None:
            written_keys.append(key)

        def list_dates(self) -> list[str]:
            return ["2026-03-21"]

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "test-bucket")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://test.endpoint")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(public_site, "_public_r2_client", lambda settings: FakeR2Client())
    settings = load_settings()
    run_at = datetime(2026, 3, 21, 8, 1, 10, tzinfo=ZoneInfo("Asia/Seoul"))

    publish_public_brief(
        packet=_packet(),
        briefing=_briefing(),
        run_at=run_at,
        settings=settings,
    )

    assert "briefs/2026-03-21.json" in written_keys
