from __future__ import annotations

import json
from types import SimpleNamespace

from morning_brief.briefing import (
    _fallback_brief,
    _improve_readability_spacing,
    _inject_quality_notice,
    generate_briefing,
)
from morning_brief.config import load_settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.observability import PipelineObserver


def test_inject_quality_notice_under_title():
    packet = {
        "data_quality": {
            "status": "critical",
            "warnings": ["가격 데이터 부족", "뉴스 부족"],
        }
    }
    text = "Morning Market Brief (2026-03-12)\n\n1. 거시 환경\n본문"

    updated = _inject_quality_notice(text, packet)

    assert "[데이터 품질 알림]" in updated
    lines = updated.splitlines()
    assert lines[0].startswith("Morning Market Brief")
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
    text = "Morning Market Brief (2026-03-12)\n\n1. 거시 환경\n금리는 올랐어요. 달러도 강했어요."

    updated = _improve_readability_spacing(text)

    assert "금리는 올랐어요.\n\n달러도 강했어요." in updated


def test_fallback_brief_mentions_official_btc_etf_flow_when_available():
    packet = {
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "bitcoin": {
            "spot": {"price": 80_000.0, "change_pct": 1.5},
            "etf_points": [],
            "etf_total_volume": 123_456,
            "official_etf_supported_tickers": ["IBIT", "BITB", "GBTC"],
            "official_etf_compared_tickers": ["IBIT", "BITB", "GBTC"],
            "official_etf_total_btc": 981_234.56,
            "official_etf_daily_flow_btc": 1_234.56,
            "official_etf_daily_flow_usd": 98_764_800.0,
        },
        "news": [],
        "data_quality": {"status": "ok", "warnings": []},
    }

    briefing = _fallback_brief(packet=packet, timezone="Asia/Seoul")

    assert "1. LAYER 1 | 오늘 한줄 판단" in briefing
    assert "2. LAYER 2 | 주요 뉴스" in briefing
    assert "3. LAYER 3 | 종목 브리핑" in briefing
    assert "981,234.56 BTC" in briefing
    assert "IBIT, BITB, GBTC 합산 보유량" in briefing
    assert "1,234.56 BTC" in briefing
    assert "직전 스냅샷 대비 순유입" in briefing


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
    draft_text = "Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n수치 체크\n- 미국 금리가 올랐습니다.\n\n해석\n성장주 멀티플이 압박받았습니다.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요."
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
    rewritten_text = "Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n수치 체크\n- 미국 금리가 올랐어요.\n\n해석\n미국 금리가 올라서, 미래 기대가 큰 기술주 주가가 부담을 받았어요.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요."

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
    draft_text = "Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n해석\n어려운 표현이 남아 있어요.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요."
    first_review_payload = {
        "pass": False,
        "rewrite_needed": True,
        "plain_language_pass": False,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": ["어려운 금융 용어가 남아 있어요."],
        "rewrite_guidance": ["쉬운 한국어로 다시 써 주세요."],
    }
    rewritten_text = "Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n해석\n쉬운 한국어로 바꿨어요.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요."
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
            "Morning Market Brief (2026-03-14)\n\n"
            "1. LAYER 1 | 오늘 한줄 판단\n"
            "핵심 판단\n"
            "미국 시장은 혼조 흐름을 보였어요. [출처: test]\n\n"
            "2. LAYER 2 | 주요 뉴스\n"
            "- 엔비디아 | AI 투자 기대가 유지됐어요. | https://example.com/nvda\n\n"
            "3. LAYER 3 | 종목 브리핑\n"
            "- 비트코인 | +1.10% | 82,000달러 안팎에서 거래됐어요. | [출처: test]"
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
    assert "오늘 한줄 판단" in briefing
    assert usage.requests == 1
    assert usage.input_tokens == 300
    assert usage.output_tokens == 120
    assert usage.cached_input_tokens == 80
    assert usage.reasoning_tokens == 10


def test_generate_briefing_respects_validator_no_rewrite_guidance(monkeypatch):
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
    draft_text = "Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n해석\n사람 확인이 필요해요.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요."
    review_payload = {
        "pass": False,
        "rewrite_needed": False,
        "plain_language_pass": True,
        "numeric_consistency_pass": False,
        "structure_pass": True,
        "issues": ["숫자 해석은 사람 확인이 필요해요."],
        "rewrite_guidance": [],
    }

    calls: list[dict] = []
    responses = [
        SimpleNamespace(output_text=draft_text, usage=None),
        SimpleNamespace(output_text=json.dumps(review_payload, ensure_ascii=False), usage=None),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr("morning_brief.briefing.OpenAI", lambda **_: fake_client)

    briefing = generate_briefing(packet=packet, settings=settings)

    assert briefing == draft_text
    assert len(calls) == 2


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
    draft_text = (
        "Morning Market Brief (2026-03-14)\n\n"
        "1. LAYER 1 | 오늘 한줄 판단\n"
        "핵심 판단\n"
        "미국 시장은 혼조 흐름을 보였어요.\n\n"
        "2. LAYER 2 | 주요 뉴스\n"
        "- 주요 뉴스 없음 | 추가 해석 없음 | 출처 없음\n\n"
        "3. LAYER 3 | 종목 브리핑\n"
        "- 주요 종목 데이터 없음 | 0.00% | 출처 없음"
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

    assert briefing == draft_text
    assert len(calls) == 2


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
            output_text="Morning Market Brief (2026-03-13)\n\n1. 거시 환경\n해석\n조용했어요.\n\n2. 미국 증시 흐름\n해석\n조용했어요.\n\n3. AI / 빅테크 동향\n해석\n조용했어요.\n\n4. 비트코인 시장\n해석\n조용했어요.\n\n5. 중요한 뉴스\n핵심 내용\n- 없음\n\n6. 시장 해석\n해석\n조용했어요.",
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
