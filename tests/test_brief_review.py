from __future__ import annotations

from morning_brief.brief_review import _parse_review_payload_text


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
