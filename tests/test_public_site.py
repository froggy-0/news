from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import morning_brief.public_site as public_site
from morning_brief.config import load_settings
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
    assert {"US10Y", "DXY", "VIX", "KRW", "NQ1!", "SPX", "QQQ", "SOXX", "BTC"} <= symbols
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
                "topic": "ai_bigtech",
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
    packet["us_indices"] = []

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
