from __future__ import annotations

from types import SimpleNamespace

from morning_brief.brief_review import _parse_review_payload_text, _review_briefing
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
