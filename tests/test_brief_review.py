from __future__ import annotations

import json
from types import SimpleNamespace

from morning_brief.brief_review import (
    _parse_review_payload_text,
    _review_briefing,
    validate_and_rewrite_briefing,
)
from morning_brief.config import load_settings
from morning_brief.observability import PipelineObserver


def test_parse_review_payload_text_accepts_code_fenced_json() -> None:
    payload = _parse_review_payload_text(
        response_text="""```json
        {
          "pass": false,
          "rewrite_needed": true,
          "plain_language_pass": true,
          "numeric_consistency_pass": true,
          "structure_pass": false,
          "issues": ["LAYER 2 형식을 맞춰야 합니다."],
          "rewrite_guidance": ["뉴스 항목 형식을 정리하세요."]
        }
        ```"""
    )

    assert payload is not None
    assert payload["rewrite_needed"] is True
    assert payload["issues"] == ["LAYER 2 형식을 맞춰야 합니다."]


def test_parse_review_payload_text_accepts_json_with_prefix_suffix() -> None:
    payload = _parse_review_payload_text(
        response_text="""
        검수 결과입니다.
        {
          "pass": true,
          "rewrite_needed": false,
          "plain_language_pass": true,
          "numeric_consistency_pass": true,
          "structure_pass": true,
          "issues": [],
          "rewrite_guidance": []
        }
        감사합니다.
        """
    )

    assert payload is not None
    assert payload["pass"] is True
    assert payload["rewrite_guidance"] == []


def test_review_briefing_retries_when_validator_hits_max_output_tokens(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path)
    packet = {
        "news": [],
        "macro": [],
        "bitcoin": {},
        "data_quality": {"status": "ok", "warnings": []},
    }
    calls: list[dict] = []
    responses = [
        SimpleNamespace(
            output_text='{"pass": false',
            usage=None,
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        ),
        SimpleNamespace(
            output_text=(
                '{"pass": true, "rewrite_needed": false, "plain_language_pass": true, '
                '"numeric_consistency_pass": true, "structure_pass": true, "issues": [], '
                '"rewrite_guidance": []}'
            ),
            usage=None,
            status="completed",
            incomplete_details=None,
        ),
    ]

    def _create(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    client = SimpleNamespace(responses=SimpleNamespace(create=_create))

    review = _review_briefing(
        draft_text="초안",
        packet=packet,
        settings=settings,
        client=client,
        observer=observer,
    )

    assert review is not None
    assert review["pass"] is True
    assert len(calls) == 2
    assert calls[0]["max_output_tokens"] == 4000
    assert calls[1]["max_output_tokens"] == 8000
    assert any(event["event"] == "brief_review_retry" for event in observer.events)


def _section_brief(body: str = "미국 시장은 금리 부담 속에서도 반도체 중심으로 버텼습니다.") -> str:
    return f"""SOVEREIGN BRIEF (2026-03-23)

Section 0. 오늘의 판단
오늘은 관망 우위입니다.
{body}

Section 1. 거시
- 미국 10년물 4.25%

Section 2. 미국 증시 흐름
- SPY +0.5%

Section 3. 주요 기술주
- NVDA +1.2%

Section 4-1. 비트코인과 ETF
- BTC 85,000달러

Section 4-2. 핵심 뉴스
① Reuters 기사

Section 4-3. 공식 X 시그널
① 공식 채널 코멘트

Section 5-1. 브리핑 지도
- 금리

Section 5-2. 핵심 뉴스 해설
- 금리 재상승은 성장주에 부담입니다.

Section 5-3. 공식 X 시그널 해설
- 공식 시그널은 반도체 투자심리를 지지합니다.

Section 6. 이벤트
- 특별 이벤트 없음
"""


def test_validate_and_rewrite_briefing_keeps_valid_section_brief_without_rewrite(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path)
    packet = {
        "news": [],
        "macro": [],
        "bitcoin": {},
        "data_quality": {"status": "ok", "warnings": []},
    }
    draft_text = _section_brief()
    calls: list[dict] = []
    review_payload = {
        "pass": True,
        "rewrite_needed": False,
        "plain_language_pass": True,
        "numeric_consistency_pass": True,
        "structure_pass": True,
        "issues": [],
        "rewrite_guidance": [],
    }

    def _create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(review_payload, ensure_ascii=False),
            usage=None,
            status="completed",
            incomplete_details=None,
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    result = validate_and_rewrite_briefing(
        draft_text=draft_text,
        packet=packet,
        settings=settings,
        client=client,
        observer=observer,
    )

    assert result == draft_text
    assert len(calls) == 1


def test_validate_and_rewrite_briefing_rewrites_only_when_section_is_structurally_broken(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BRIEF_MAX_REWRITES", "1")
    settings = load_settings()
    observer = PipelineObserver(output_dir=tmp_path)
    packet = {
        "news": [],
        "macro": [],
        "bitcoin": {},
        "data_quality": {"status": "ok", "warnings": []},
    }
    draft_text = _section_brief().replace("Section 4-2. 핵심 뉴스\n① Reuters 기사\n\n", "")
    rewritten_text = _section_brief(body="재작성 후 섹션 구조를 복구했습니다.")
    review_fail = {
        "pass": False,
        "rewrite_needed": True,
        "plain_language_pass": True,
        "numeric_consistency_pass": True,
        "structure_pass": False,
        "issues": ["Section 4-2가 누락됐습니다."],
        "rewrite_guidance": ["Section 4-2를 복구하세요."],
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
    responses = [
        SimpleNamespace(
            output_text=json.dumps(review_fail, ensure_ascii=False),
            usage=None,
            status="completed",
            incomplete_details=None,
        ),
        SimpleNamespace(
            output_text=rewritten_text,
            usage=None,
            status="completed",
            incomplete_details=None,
        ),
        SimpleNamespace(
            output_text=json.dumps(review_pass, ensure_ascii=False),
            usage=None,
            status="completed",
            incomplete_details=None,
        ),
    ]

    def _create(**_kwargs):
        return responses.pop(0)

    client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    result = validate_and_rewrite_briefing(
        draft_text=draft_text,
        packet=packet,
        settings=settings,
        client=client,
        observer=observer,
    )

    assert "Section 4-2. 핵심 뉴스" in result
    assert "재작성 후 섹션 구조를 복구했습니다." in result
