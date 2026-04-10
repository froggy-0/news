from __future__ import annotations

import json
from types import SimpleNamespace

from morning_brief.briefing import (
    _append_reference_block,
    _brief_structure_issues,
    _fallback_brief,
    _fallback_if_incomplete,
    _fallback_news_lines,
    _improve_readability_spacing,
    _inject_quality_notice,
    generate_briefing,
)
from morning_brief.config import load_settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.observability import PipelineObserver


def _complete_layered_brief(
    *,
    title_date: str = "2026-03-13",
    layer_one_body: str = "금리와 기술주 흐름을 함께 봐야 합니다.",
    layer_three_body: str | None = None,
) -> str:
    stock_block = layer_three_body or (
        "- NVDA | +1.20% | 데이터센터 투자 기대가 이어졌습니다. | [출처: KIS]\n"
        "- AMD | -0.80% | 반도체 종목 안에서도 차이가 있었습니다. | [출처: KIS]\n"
    )
    return f"""SOVEREIGN BRIEF ({title_date})

0. 오늘의 핵심
{layer_one_body}

1. 거시 지표 Dashboard
- 미국 10년물 국채금리: 4.10% (+0.20%) (전일 값)

2. 미국 증시
{stock_block}
- AAPL | +1.10% | 주요 기대
- AMZN | -0.10% | 주요 기대
- MSFT | +1.90% | 주요 기대
- META | -1.10% | 주요 기대
- GOOGL | +0.20% | 주요 기대
- TSLA | +2.20% | 주요 기대
- AVGO | -1.50% | 주요 기대
- ASML | -0.90% | 주요 기대

3. BTC & 크립토
- 비트코인 현물은 82,000달러였습니다. [출처: CoinGecko]

4-1. 이슈 브리핑
금리와 기술주, 비트코인 흐름을 함께 비교할 필요가 있습니다.

4-2. 핵심 뉴스 5선
① Nvidia unveils new AI cluster — 뉴스출처
AI 투자 기대를 다시 자극했습니다.
→ 원문 링크 https://www.reuters.com/world/us/example
핵심 한줄: Nvidia

② Bitcoin ETF inflows resume — 뉴스출처
비트코인 ETF 수급 개선을 같이 봐야 합니다.
→ 원문 링크 https://www.cnbc.com/example
핵심 한줄: Bitcoin

4-3. 섹터/자산 영향 매핑
수혜 방향
- NVDA

5-1. 주간 맥락 연결
- 흐름 요약

6. 이벤트 캘린더
10/12 뉴스
"""


def test_inject_quality_notice_under_title():
    packet = {
        "data_quality": {
            "status": "critical",
            "warnings": ["가격 데이터 부족", "뉴스 부족"],
        }
    }
    text = "SOVEREIGN BRIEF (2026-03-12)\n\n1. 거시 환경\n본문"

    updated = _inject_quality_notice(text, packet)

    assert "[데이터 품질 알림]" in updated
    lines = updated.splitlines()
    assert lines[0].startswith("SOVEREIGN BRIEF")
    assert lines[1].startswith("[데이터 품질 알림]")


def test_generate_briefing_raises_when_prompt_rendering_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "etf_total_volume": 0},
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    monkeypatch.setattr(
        "morning_brief.briefing.render_brief_prompts",
        lambda **_: (_ for _ in ()).throw(RuntimeError("template missing")),
    )

    try:
        generate_briefing(packet=packet, settings=settings)
    except BriefGenerationError as exc:
        assert "template missing" in str(exc)
    else:
        raise AssertionError("BriefGenerationError was expected")


def test_improve_readability_spacing_breaks_sentences():
    text = "SOVEREIGN BRIEF (2026-03-12)\n\n1. 거시 환경\n금리는 올랐어요. 달러도 강했어요."

    updated = _improve_readability_spacing(text)

    assert "금리는 올랐어요.\n\n달러도 강했어요." in updated


def test_fallback_brief_renders_rate_changes_in_basis_points():
    packet = {
        "macro": [
            {
                "label": "미국 10년물 국채금리",
                "canonical_key": "us10y",
                "price": 4.25,
                "change_pct": None,
                "change_bps": 4.0,
            }
        ],
        "korea_watch": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "official_etf_snapshots": []},
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "전일 대비 +4bp" in briefing
    assert "+4.00%" not in briefing


def test_fallback_brief_mentions_official_btc_etf_holdings_when_available():
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 80_000.0, "change_pct": 1.5},
            "etf_points": [],
            "official_etf_snapshots": [
                {"issuer": "BlackRock", "ticker": "IBIT", "total_btc": 300_000.0, "aum_usd": 10.0}
            ],
            "official_etf_total_btc": 981_234.56,
            "official_etf_total_aum_usd": 98_764_800.0,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "0. 오늘의 핵심" in briefing
    assert "1. 거시 지표 Dashboard" in briefing
    assert "2. 미국 증시" in briefing
    assert "981,234.56 BTC" in briefing
    assert "공식 발행사 기준 총 981,234.56 BTC" in briefing
    assert "98,764,800달러" in briefing
    assert "순유입" not in briefing


def test_brief_structure_issues_accepts_layer_two_bullets_outside_metrics_label():
    brief = """SOVEREIGN BRIEF (2026-03-14)

1. LAYER 1 | 오늘 한줄 판단
한줄 결론
- 오늘은 관망 국면입니다.

2. LAYER 2 | 주요 뉴스
왜 중요한지
- Nvidia가 AI 투자 기대를 자극했습니다. | 반도체 투자 심리에 직접 연결됩니다. | 국내 투자자는 반도체주 반응을 같이 볼 필요가 있습니다.
- 비트코인 ETF 흐름이 다시 개선됐습니다. | 수급 심리 회복 여부를 판단하는 재료입니다. | 국내 투자자는 관련주 변동성도 함께 볼 필요가 있습니다.

3. LAYER 3 | 종목 브리핑
쉽게 보면
- NVDA는 AI 수요 기대가 이어지며 1.20% 상승했습니다. [출처: KIS]
- AMD는 반도체 내 종목별 차이가 나타나며 0.80% 하락했습니다. [출처: KIS]
"""

    issues = _brief_structure_issues(brief)

    assert not any("LAYER 2" in issue for issue in issues)


def test_brief_structure_issues_does_not_fail_only_for_missing_macro_subheading():
    brief = """SOVEREIGN BRIEF (2026-03-14)

1. LAYER 1 | 오늘 한줄 판단
핵심 판단
- 오늘은 관망 국면입니다.

2. LAYER 2 | 주요 뉴스
핵심 이슈
- Nvidia 투자 확대 | AI 투자 기대를 자극했습니다. | 국내 투자자는 반도체주 반응을 같이 볼 필요가 있습니다.
- 비트코인 ETF 유입 | 수급 심리를 판단하는 재료입니다. | 국내 투자자는 관련주 변동성도 함께 볼 필요가 있습니다.

3. LAYER 3 | 종목 브리핑
주요 지표
- NVDA는 AI 투자 기대가 이어지며 1.20% 상승했습니다. [출처: KIS]
- AMD는 종목별 차이가 나타나며 0.80% 하락했습니다. [출처: KIS]
"""

    issues = _brief_structure_issues(brief)

    assert "LAYER 3 안에 거시 지표 소제목이 없어요." not in issues


def test_fallback_brief_marks_previous_values_and_appends_footer_notes():
    packet = {
        "macro": [
            {
                "label": "달러 인덱스",
                "price": 104.2,
                "resolved_value": 104.2,
                "change_pct": 0.3,
                "is_previous_value": True,
                "validation_status": "previous_value",
            }
        ],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {
                "price": 80_000.0,
                "resolved_value": 80_000.0,
                "change_pct": 1.5,
                "is_previous_value": True,
                "validation_status": "previous_value",
            },
            "etf_points": [],
            "etf_total_volume": None,
            "official_etf_supported_tickers": [],
            "official_etf_compared_tickers": [],
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
            "official_etf_daily_flow_usd": None,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
        "data_footer_notes": ["달러 인덱스는 허용 범위를 벗어나 생략했어요."],
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "(전일 값)" in briefing
    assert "데이터 처리 메모" in briefing
    assert "달러 인덱스는 허용 범위를 벗어나 생략했어요." in briefing


def test_fallback_brief_includes_korean_investor_signals():
    packet = {
        "macro": [
            {
                "label": "미국 10년물 국채금리",
                "ticker": "DGS10",
                "price": 4.1,
                "resolved_value": 4.1,
                "change_pct": 0.2,
                "canonical_key": "us10y",
            },
            {
                "label": "VIX",
                "ticker": "VIXCLS",
                "price": 17.5,
                "resolved_value": 17.5,
                "change_pct": -1.1,
                "canonical_key": "vix",
            },
        ],
        "korea_watch": [
            {
                "label": "원/달러 환율",
                "ticker": "KRW=X",
                "price": 1330.5,
                "resolved_value": 1330.5,
                "change_pct": 0.12,
                "canonical_key": "usdkrw",
            },
            {
                "label": "나스닥 선물",
                "ticker": "NQ=F",
                "price": 20150.0,
                "resolved_value": 20150.0,
                "change_pct": 0.48,
                "canonical_key": "nq_futures",
            },
        ],
        "us_indices": [
            {
                "label": "S&P500",
                "ticker": "SPY",
                "price": 610.2,
                "resolved_value": 610.2,
                "change_pct": 0.9,
                "canonical_key": "spy",
            }
        ],
        "tech_stocks": [
            {
                "label": "AVGO",
                "ticker": "AVGO",
                "price": 150.0,
                "resolved_value": 150.0,
                "change_pct": -4.11,
                "canonical_key": "avgo",
            }
        ],
        "bitcoin": {
            "spot": {
                "label": "BTC-USD",
                "ticker": "BTC-USD",
                "price": 71_282.0,
                "resolved_value": 71_282.0,
                "change_pct": -0.16,
                "canonical_key": "btc",
            },
            "etf_points": [],
            "etf_total_volume": None,
            "fear_greed_value": 60,
            "fear_greed_label": "탐욕",
            "official_etf_supported_tickers": [],
            "official_etf_compared_tickers": [],
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
            "official_etf_daily_flow_usd": None,
        },
        "news": [{"topic": "us_equity", "title": "Example", "why_it_matters": "AI 투자 기대"}],
        "data_quality": {"status": "ok", "warnings": []},
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "오늘은 매수 관심 국면입니다." in briefing
    assert "원/달러 환율은 1,330.50원으로 전일 대비 +0.12%였습니다." in briefing
    assert "나스닥 선물은 전일 대비 +0.48%로 상승 방향입니다." in briefing
    assert "원/달러 환율은 1,330.50원으로 전일 대비 +0.12%였습니다. [출처: yfinance]" in briefing
    assert "나스닥 선물은 전일 대비 +0.48%로 상승 방향입니다. [출처: yfinance]" in briefing
    assert "공포탐욕지수는 60로 탐욕 구간입니다." not in briefing
    assert "공포탐욕지수는 60으로 탐욕 구간입니다." in briefing
    assert "오늘 미국 증시 흐름이 코스피에 미치는 영향:" in briefing
    assert "AVGO은" not in briefing
    assert "AVGO는" in briefing


def test_fallback_brief_marks_kis_source_for_usdkrw_primary():
    packet = {
        "macro": [],
        "korea_watch": [
            {
                "label": "원/달러 환율",
                "ticker": "USDKRW",
                "price": 1330.5,
                "resolved_value": 1330.5,
                "change_pct": 0.12,
                "canonical_key": "usdkrw",
            },
            {
                "label": "나스닥 선물",
                "ticker": "NQ=F",
                "price": 20150.0,
                "resolved_value": 20150.0,
                "change_pct": 0.48,
                "canonical_key": "nq_futures",
            },
        ],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {},
            "etf_points": [],
            "fear_greed_value": 60,
            "fear_greed_label": "탐욕",
            "official_etf_supported_tickers": [],
            "official_etf_compared_tickers": [],
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
            "official_etf_daily_flow_usd": None,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "원/달러 환율은 1,330.50원으로 전일 대비 +0.12%였습니다. [출처: KIS]" in briefing
    assert "나스닥 선물은 전일 대비 +0.48%로 상승 방향입니다. [출처: yfinance]" in briefing


def test_append_reference_block_includes_news_item_urls():
    text = "SOVEREIGN BRIEF (2026-03-14)\n\n1. LAYER 1 | 오늘 한줄 판단\n본문"
    packet = {
        "news": [
            {
                "title": "Nvidia unveils new AI cluster",
                "url": "https://www.reuters.com/world/us/example",
                "citations": ["https://www.reuters.com/world/us/example"],
            }
        ]
    }

    updated = _append_reference_block(text, packet)

    assert "참고 출처" in updated
    assert "- Nvidia unveils new AI cluster — https://www.reuters.com/world/us/example" in updated


def test_generate_briefing_rewrites_when_validator_finds_plain_language_issue(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [{"label": "US10Y", "price": 4.1, "change_pct": 0.1}],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 82_000.0, "change_pct": 1.1},
            "etf_points": [],
            "etf_total_volume": 0,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }
    draft_text = _complete_layered_brief(layer_one_body="성장주 멀티플이 압박받았습니다.")
    review_payload = {
        "pass": False,
        "rewrite_needed": True,
        "plain_language_pass": False,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": ["어려운 금융 용어가 남아 있어요."],
        "rewrite_guidance": ["'성장주 멀티플' 같은 표현을 쉬운 한국어로 바꿔 주세요."],
    }
    pass_review_payload = {
        "pass": True,
        "rewrite_needed": False,
        "plain_language_pass": True,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": [],
        "rewrite_guidance": [],
    }
    rewritten_text = _complete_layered_brief(
        layer_one_body="미래 기대가 큰 기술주 주가가 부담을 받았어요."
    )

    calls: list[dict] = []
    responses = [
        SimpleNamespace(output_text=draft_text, usage=None),
        SimpleNamespace(output_text=json.dumps(review_payload, ensure_ascii=False), usage=None),
        SimpleNamespace(output_text=rewritten_text, usage=None),
        SimpleNamespace(
            output_text=json.dumps(pass_review_payload, ensure_ascii=False), usage=None
        ),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings)

    assert "미래 기대가 큰 기술주 주가가 부담을 받았어요." in briefing
    assert "성장주 멀티플이 압박받았습니다." not in briefing
    assert len(calls) == 4
    assert calls[1]["text"]["format"]["type"] == "json_schema"


def test_generate_briefing_falls_back_when_draft_structure_is_incomplete(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [{"label": "US10Y", "price": 4.1, "change_pct": 0.1}],
        "us_indices": [],
        "tech_stocks": [
            {"label": "NVDA", "price": 120.0, "change_pct": 1.2},
            {"label": "AMD", "price": 140.0, "change_pct": -0.8},
        ],
        "bitcoin": {
            "spot": {"price": 82_000.0, "change_pct": 1.1},
            "etf_points": [],
            "etf_total_volume": 123_456,
            "official_etf_supported_tickers": [],
            "official_etf_compared_tickers": [],
            "official_etf_total_btc": None,
            "official_etf_daily_flow_btc": None,
            "official_etf_daily_flow_usd": None,
        },
        "news": [
            {
                "title": "Nvidia unveils new AI cluster",
                "url": "https://www.reuters.com/world/us/example",
                "citations": ["https://www.reuters.com/world/us/example"],
                "why_it_matters": "AI 투자 기대를 다시 자극한 기사입니다.",
            },
            {
                "title": "Bitcoin ETF inflows resume",
                "url": "https://www.cnbc.com/example",
                "citations": ["https://www.cnbc.com/example"],
                "why_it_matters": "비트코인 ETF 수급 해석에 바로 연결됩니다.",
            },
            {
                "title": "Treasury yields stay firm",
                "url": "https://www.wsj.com/example",
                "citations": ["https://www.wsj.com/example"],
                "why_it_matters": "금리 흐름을 이해하는 데 필요한 기사입니다.",
            },
        ],
        "data_quality": {"status": "ok", "warnings": []},
    }
    truncated_draft = """SOVEREIGN BRIEF (2026-03-13)

0. 오늘의 핵심
- 금리와 기술주 흐름이 함께 관찰됐습니다.

1. 거시 지표 Dashboard
- 미국 10년물 금리는 4.10%였습니다. [출처: FRED]

2. 미국 증시
- NVDA | +1.20% |"""

    responses = [
        SimpleNamespace(output_text=truncated_draft, usage=None),
        SimpleNamespace(
            output_text='{"pass":false,"rewrite_needed":true,"issues":["LAYER 3 truncated',
            usage=None,
        ),
    ]

    def _create(**_kwargs):
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings)

    assert "0. 오늘의 핵심" in briefing
    assert "1. 거시 지표 Dashboard" in briefing
    assert "2. 미국 증시" in briefing
    assert "주요 종목 등락률은 이번 집계에서 충분히 확인되지 않았습니다." not in briefing


def test_generate_briefing_revalidates_after_rewrite(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BRIEF_MAX_REWRITES", "2")
    settings = load_settings()
    packet = {
        "macro": [{"label": "US10Y", "price": 4.1, "change_pct": 0.1}],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 82_000.0, "change_pct": 1.1},
            "etf_points": [],
            "etf_total_volume": 0,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }
    draft_text = _complete_layered_brief(layer_one_body="어려운 표현이 남아 있어요.")
    first_review_payload = {
        "pass": False,
        "rewrite_needed": True,
        "plain_language_pass": False,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": ["어려운 금융 용어가 남아 있어요."],
        "rewrite_guidance": ["쉬운 한국어로 다시 써 주세요."],
    }
    rewritten_text = _complete_layered_brief(layer_one_body="쉬운 한국어로 바꿨어요.")
    second_review_payload = {
        "pass": True,
        "rewrite_needed": False,
        "plain_language_pass": True,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": [],
        "rewrite_guidance": [],
    }

    calls: list[dict] = []
    responses = [
        SimpleNamespace(output_text=draft_text, usage=None),
        SimpleNamespace(
            output_text=json.dumps(first_review_payload, ensure_ascii=False), usage=None
        ),
        SimpleNamespace(output_text=rewritten_text, usage=None),
        SimpleNamespace(
            output_text=json.dumps(second_review_payload, ensure_ascii=False), usage=None
        ),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings)

    assert "쉬운 한국어로 바꿨어요." in briefing
    assert len(calls) == 4
    assert calls[3]["text"]["format"]["type"] == "json_schema"


def test_generate_briefing_records_cached_input_tokens_in_observer(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BRIEF_VALIDATION_ENABLED", "false")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 82_000.0, "change_pct": 1.1},
            "etf_points": [],
            "etf_total_volume": None,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }
    response = SimpleNamespace(
        output_text=(
            "SOVEREIGN BRIEF (2026-03-14)\n\n"
            "0. 오늘의 핵심\n"
            "미국 시장은 혼조 흐름을 보였어요. [출처: test]\n\n"
            "1. 거시 지표 Dashboard\n"
            "- 달러\n\n"
            "2. 미국 증시\n"
            "- 1 | +1.1%\n"
            "- 2 | -0.1%\n"
            "- 3 | +1.1%\n"
            "- 4 | -0.1%\n"
            "- 5 | +1.1%\n"
            "- 6 | -0.1%\n"
            "- 7 | +1.1%\n"
            "- 8 | -0.1%\n"
            "3. BTC & 크립토\n"
            "- 비트코인 | +1.10% | 82,000달러 안팎에서 거래됐어요. | [출처: test]\n"
            "4-2. 핵심 뉴스 5선\n"
            "① 뉴스 1\n"
            "② 뉴스 2\n"
            "6. 이벤트 캘린더\n"
            "이벤트 없음"
        ),
        usage=SimpleNamespace(
            input_tokens=300,
            output_tokens=120,
            input_tokens_details=SimpleNamespace(cached_tokens=80),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        ),
    )

    def _create(**_: object) -> SimpleNamespace:
        return response

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    observer = PipelineObserver(output_dir=tmp_path)
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings, observer=observer)

    usage = observer.provider_usage["openai"]
    assert "미국 시장은 혼조" in briefing
    assert usage.requests == 1
    assert usage.input_tokens == 300
    assert usage.output_tokens == 120
    assert usage.cached_input_tokens == 80
    assert usage.reasoning_tokens == 10


def test_generate_briefing_rewrites_when_validator_returns_failed_review_without_guidance(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "etf_total_volume": 0},
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }
    draft_text = _complete_layered_brief(layer_one_body="수치 해석이 어긋난 초안입니다.")
    rewritten_text = _complete_layered_brief(layer_one_body="수치 해석을 다시 맞춘 최종안입니다.")
    review_fail = {
        "pass": False,
        "rewrite_needed": False,
        "plain_language_pass": True,
        "numeric_consistency_pass": False,
        "structure_pass": True,
        "issues": ["수치와 해석이 어긋난 문장을 바로잡아 주세요."],
        "rewrite_guidance": [],
    }
    review_pass = {
        "pass": True,
        "rewrite_needed": False,
        "plain_language_pass": True,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": [],
        "rewrite_guidance": [],
    }

    calls: list[dict] = []
    responses = [
        SimpleNamespace(output_text=draft_text, usage=None),
        SimpleNamespace(output_text=json.dumps(review_fail, ensure_ascii=False), usage=None),
        SimpleNamespace(output_text=rewritten_text, usage=None),
        SimpleNamespace(output_text=json.dumps(review_pass, ensure_ascii=False), usage=None),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings)

    assert briefing.strip() == rewritten_text.strip()
    assert len(calls) == 4


def test_generate_briefing_keeps_draft_when_validator_json_is_invalid(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "etf_total_volume": 0},
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }
    draft_text = _complete_layered_brief(
        title_date="2026-03-14",
        layer_one_body="미국 시장은 혼조 흐름을 보였어요.",
    )
    malformed_review = '{"pass": false, "rewrite_needed": true, "issues": ["문장 길이를 줄여 주세요'

    calls: list[dict] = []
    responses = [
        SimpleNamespace(output_text=draft_text, usage=None),
        SimpleNamespace(output_text=malformed_review, usage=None),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings)

    assert briefing.strip() == draft_text.strip()
    assert len(calls) == 2


def test_brief_structure_issues_flags_partially_truncated_news_section():
    brief = """SOVEREIGN BRIEF (2026-03-19)

0. 오늘의 핵심
핵심 요약입니다.

1. 거시 지표 Dashboard
- 미국 10년물 국채금리: 4.10% (+0.20%)

2. 미국 증시
- NVDA | +1.20% | 데이터센터 투자 기대

3. BTC & 크립토
- 비트코인 현물은 82,000달러였습니다.

4-2. 핵심 뉴스 5선
① 첫 번째 뉴스 — Reuters
설명입니다.
→ 원문 링크 https://www.reuters.com/world/us/example1
핵심 한줄: 첫 번째

② 두 번째 뉴스 — CNBC
설명입니다.
→ 원문 링크 https://www.cnbc.com/example2
핵심 한줄: 두 번째

③ 세 번째 뉴스 — WSJ
설명입니다.
→ 원문 링크 https://www.wsj.com/example3
핵심 한줄: 세 번째

④ 네 번째 뉴스 — Bloomberg

6. 이벤트 캘린더
없음
"""

    issues = _brief_structure_issues(brief)

    assert any(
        ("핵심 뉴스 항목 일부가 중간에 잘려" in issue)
        or ("핵심 뉴스 항목 일부가 불완전해요." in issue)
        for issue in issues
    )


def test_fallback_if_incomplete_replaces_truncated_news_section():
    packet = {
        "macro": [],
        "korea_watch": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 82_000.0, "change_pct": 1.1},
            "etf_points": [],
            "etf_total_volume": 0,
        },
        "news": [
            {
                "title": "Nvidia unveils new AI cluster",
                "url": "https://www.reuters.com/world/us/example",
                "citations": ["https://www.reuters.com/world/us/example"],
                "why_it_matters": "AI 투자 기대를 다시 자극한 기사입니다.",
            },
            {
                "title": "Bitcoin ETF inflows resume",
                "url": "https://www.cnbc.com/example",
                "citations": ["https://www.cnbc.com/example"],
                "why_it_matters": "비트코인 ETF 수급 해석에 바로 연결됩니다.",
            },
            {
                "title": "Treasury yields stay firm",
                "url": "https://www.wsj.com/example",
                "citations": ["https://www.wsj.com/example"],
                "why_it_matters": "금리 흐름을 이해하는 데 필요한 기사입니다.",
            },
        ],
        "data_quality": {"status": "ok", "warnings": []},
    }
    truncated = """SOVEREIGN BRIEF (2026-03-19)

0. 오늘의 핵심
핵심 요약입니다.

1. 거시 지표 Dashboard
- 미국 10년물 국채금리: 4.10% (+0.20%)

2. 미국 증시
- NVDA | +1.20% | 데이터센터 투자 기대

3. BTC & 크립토
- 비트코인 현물은 82,000달러였습니다.

4-2. 핵심 뉴스 5선
① 첫 번째 뉴스 — Reuters
설명입니다.
→ 원문 링크 https://www.reuters.com/world/us/example
핵심 한줄: 첫 번째

② 두 번째 뉴스 — CNBC
설명입니다.
→ 원문 링크 https://www.cnbc.com/example
핵심 한줄: 두 번째

④ 네 번째 뉴스 — Bloomberg

6. 이벤트 캘린더
없음
"""

    repaired = _fallback_if_incomplete(
        text=truncated,
        packet=packet,
        settings=load_settings(),
    )

    assert "④ Grayscale" not in repaired
    assert "Treasury yields stay firm" in repaired
    assert "→ 원문 링크 https://www.wsj.com/example" in repaired


def test_generate_briefing_skips_review_when_generation_response_is_incomplete(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    packet = {
        "macro": [],
        "korea_watch": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 82_000.0, "change_pct": 1.1},
            "etf_points": [],
            "etf_total_volume": 0,
        },
        "news": [
            {
                "title": "Nvidia unveils new AI cluster",
                "url": "https://www.reuters.com/world/us/example",
                "citations": ["https://www.reuters.com/world/us/example"],
                "why_it_matters": "AI 투자 기대를 다시 자극한 기사입니다.",
            },
            {
                "title": "Bitcoin ETF inflows resume",
                "url": "https://www.cnbc.com/example",
                "citations": ["https://www.cnbc.com/example"],
                "why_it_matters": "비트코인 ETF 수급 해석에 바로 연결됩니다.",
            },
        ],
        "data_quality": {"status": "ok", "warnings": []},
    }
    truncated_draft = """SOVEREIGN BRIEF (2026-03-19)

0. 오늘의 핵심
오늘은 관망 국면입니다.

1. 거시 지표 Dashboard
- 미국 10년물 국채금리: 4.10% (+0.20%)

2. 미국 증시
- NVDA | +1.20% | 데이터센터 투자 기대

4-2. 핵심 뉴스 5선
① 첫 번째 뉴스 — Reuters
설명입니다.
→ 원문 링크 https://www.reuters.com/world/us/example
핵심 한줄: 첫 번째
"""
    calls: list[dict] = []
    observer = PipelineObserver(output_dir=tmp_path)
    responses = [
        SimpleNamespace(
            output_text=truncated_draft,
            usage=None,
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings, observer=observer)

    assert len(calls) == 1
    assert "Bitcoin ETF inflows resume" in briefing
    assert any(event["event"] == "brief_generation_incomplete" for event in observer.events)


def test_generate_briefing_skips_validator_when_disabled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BRIEF_VALIDATION_ENABLED", "false")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "etf_total_volume": 0},
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }
    calls: list[dict] = []
    responses = [
        SimpleNamespace(
            output_text="SOVEREIGN BRIEF (2026-03-13)\n\n1. 거시 환경\n해석\n조용했어요.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요.",
            usage=None,
        )
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    generate_briefing(packet=packet, settings=settings)

    assert len(calls) == 1


def test_generate_briefing_retries_once_when_max_output_tokens_is_too_low(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BRIEF_VALIDATION_ENABLED", "false")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "2300")
    settings = load_settings()
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {"spot": {}, "etf_points": [], "etf_total_volume": 0},
        "news": [
            {
                "title": "Example one",
                "url": "https://www.reuters.com/world/us/example",
                "citations": ["https://www.reuters.com/world/us/example"],
                "why_it_matters": "AI 투자 기대를 다시 자극한 기사입니다.",
            },
            {
                "title": "Example two",
                "url": "https://www.cnbc.com/example",
                "citations": ["https://www.cnbc.com/example"],
                "why_it_matters": "비트코인 ETF 수급 해석에 바로 연결됩니다.",
            },
        ],
        "data_quality": {"status": "ok", "warnings": []},
    }
    observer = PipelineObserver(output_dir=tmp_path)
    calls: list[dict] = []
    responses = [
        SimpleNamespace(
            output_text="SOVEREIGN BRIEF (2026-03-19)\n\n0. 오늘의 핵심\n잘린 응답",
            usage=None,
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        ),
        SimpleNamespace(
            output_text=_complete_layered_brief(),
            usage=None,
            status="completed",
            incomplete_details=None,
        ),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings, observer=observer)

    assert len(calls) == 2
    assert calls[0]["max_output_tokens"] == 2300
    assert calls[1]["max_output_tokens"] == 50000
    assert "4-2. 핵심 뉴스 5선" in briefing
    assert any(event["event"] == "brief_generation_retry" for event in observer.events)


def test_fallback_news_lines_skip_file_titles_and_none_like_values():
    news = [
        {
            "title": "monetary20260318a1.htm",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a1.htm",
            "topic": "macro",
            "why_it_matters": None,
        },
        {
            "title": "Bitcoin ETF Inflows Surge to Record High",
            "url": "https://x.com/BitcoinETF",
            "topic": "bitcoin",
            "why_it_matters": None,
        },
    ]

    lines = "\n".join(_fallback_news_lines(news))

    assert "monetary20260318a1.htm" not in lines
    assert "None None" not in lines
    assert "비트코인 관련 기사 (@BitcoinETF)" in lines
    assert "Bitcoin ETF Inflows Surge to Record High" not in lines
