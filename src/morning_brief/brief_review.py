from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from morning_brief.config import Settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.observability import PipelineObserver
from morning_brief.openai_utils import cached_input_tokens, usage_snapshot
from morning_brief.prompting import (
    build_prompt_cache_key,
    render_brief_rewrite_prompts,
    render_brief_validator_prompts,
)

logger = logging.getLogger(__name__)

VALIDATOR_MAX_OUTPUT_TOKENS = 700

BRIEF_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pass": {"type": "boolean"},
        "rewrite_needed": {"type": "boolean"},
        "plain_language_pass": {"type": "boolean"},
        "numeric_consistency_pass": {"type": "boolean"},
        "structure_pass": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "rewrite_guidance": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "pass",
        "rewrite_needed",
        "plain_language_pass",
        "numeric_consistency_pass",
        "structure_pass",
        "issues",
        "rewrite_guidance",
    ],
}


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return False


def _normalize_review_payload(payload: object) -> dict:
    data = payload if isinstance(payload, dict) else {}
    return {
        "pass": _coerce_bool(data.get("pass", False)),
        "rewrite_needed": _coerce_bool(data.get("rewrite_needed", False)),
        "plain_language_pass": _coerce_bool(data.get("plain_language_pass", False)),
        "numeric_consistency_pass": _coerce_bool(data.get("numeric_consistency_pass", False)),
        "structure_pass": _coerce_bool(data.get("structure_pass", False)),
        "issues": [str(item).strip() for item in data.get("issues", []) if str(item).strip()],
        "rewrite_guidance": [
            str(item).strip() for item in data.get("rewrite_guidance", []) if str(item).strip()
        ],
    }


def _review_briefing(
    *,
    draft_text: str,
    packet: dict,
    settings: Settings,
    client: OpenAI,
    observer: PipelineObserver | None = None,
) -> dict | None:
    packet_json = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    instructions, user_prompt = render_brief_validator_prompts(
        packet_json=packet_json,
        draft_text=draft_text,
        settings=settings,
    )
    prompt_cache_key = build_prompt_cache_key(
        settings=settings,
        instructions=instructions + ":brief-validator",
        model_name=settings.openai_brief_validation_model,
    )
    started_at = time.perf_counter()
    try:
        response = client.responses.create(
            model=settings.openai_brief_validation_model,
            instructions=instructions,
            input=user_prompt,
            reasoning={"effort": "minimal"},
            max_output_tokens=VALIDATOR_MAX_OUTPUT_TOKENS,
            prompt_cache_key=prompt_cache_key,
            text={
                "verbosity": "low",
                "format": {
                    "type": "json_schema",
                    "name": "brief_review",
                    "strict": True,
                    "schema": BRIEF_REVIEW_SCHEMA,
                    "description": "Review result for the Korean morning market brief.",
                },
            },
        )
    except Exception as exc:
        raise BriefGenerationError(f"브리핑 검수 OpenAI 호출에 실패했어요: {exc}") from exc
    payload = json.loads((response.output_text or "").strip() or "{}")
    review = _normalize_review_payload(payload)
    cached_tokens = cached_input_tokens(response)
    if cached_tokens is not None:
        logger.info(
            "브리핑 검수 프롬프트 캐시를 사용했어요. key=%s | cached_input_tokens=%s",
            prompt_cache_key,
            cached_tokens,
        )
    if observer is not None:
        observer.record_provider_usage("openai", requests=1, **usage_snapshot(response))
        observer.record_phase_duration(
            "review",
            int(round((time.perf_counter() - started_at) * 1000)),
        )
    return review


def _rewrite_briefing(
    *,
    draft_text: str,
    packet: dict,
    review: dict,
    settings: Settings,
    client: OpenAI,
    observer: PipelineObserver | None = None,
) -> str:
    packet_json = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    review_json = json.dumps(review, ensure_ascii=False, separators=(",", ":"))
    instructions, user_prompt = render_brief_rewrite_prompts(
        packet_json=packet_json,
        draft_text=draft_text,
        review_json=review_json,
        settings=settings,
    )
    prompt_cache_key = build_prompt_cache_key(
        settings=settings,
        instructions=instructions + ":brief-rewrite",
        model_name=settings.openai_model,
    )
    started_at = time.perf_counter()
    try:
        response = client.responses.create(
            model=settings.openai_model,
            instructions=instructions,
            input=user_prompt,
            reasoning={"effort": settings.openai_reasoning_effort},
            max_output_tokens=settings.openai_max_output_tokens,
            prompt_cache_key=prompt_cache_key,
        )
    except Exception as exc:
        raise BriefGenerationError(f"브리핑 재작성 OpenAI 호출에 실패했어요: {exc}") from exc
    rewritten = (response.output_text or "").strip()
    if not rewritten:
        raise BriefGenerationError("검수 반영 재작성 결과가 비어 있어요.")
    cached_tokens = cached_input_tokens(response)
    if cached_tokens is not None:
        logger.info(
            "브리핑 재작성 프롬프트 캐시를 사용했어요. key=%s | cached_input_tokens=%s",
            prompt_cache_key,
            cached_tokens,
        )
    if observer is not None:
        observer.record_provider_usage("openai", requests=1, **usage_snapshot(response))
        observer.record_phase_duration(
            "review",
            int(round((time.perf_counter() - started_at) * 1000)),
        )
    return rewritten


def validate_and_rewrite_briefing(
    *,
    draft_text: str,
    packet: dict,
    settings: Settings,
    client: OpenAI,
    observer: PipelineObserver | None = None,
) -> str:
    if not settings.openai_brief_validation_enabled:
        return draft_text

    review = _review_briefing(
        draft_text=draft_text,
        packet=packet,
        settings=settings,
        client=client,
        observer=observer,
    )

    if review is None:
        return draft_text

    if review["pass"]:
        logger.info("브리핑 최종 검수를 통과했어요.")
        return draft_text

    issues = "; ".join(review["issues"][:3]) or "보완이 필요한 표현이 있었어요"
    logger.warning("브리핑 최종 검수에서 보완점을 찾았어요: %s", issues)

    if settings.openai_brief_max_rewrites <= 0:
        return draft_text
    if not review["rewrite_needed"]:
        logger.info("자동 재작성보다 사람 확인이 더 적절해 보여서 초안을 유지할게요.")
        return draft_text

    rewritten = draft_text
    current_review = review
    for attempt in range(1, settings.openai_brief_max_rewrites + 1):
        try:
            rewritten = _rewrite_briefing(
                draft_text=rewritten,
                packet=packet,
                review=current_review,
                settings=settings,
                client=client,
                observer=observer,
            )
            logger.info("검수 지적을 반영해 브리핑을 %s회 다듬었어요.", attempt)
        except BriefGenerationError:
            raise
        except Exception as exc:
            raise BriefGenerationError(f"브리핑 재작성 중 문제가 생겼어요: {exc}") from exc

        current_review = _review_briefing(
            draft_text=rewritten,
            packet=packet,
            settings=settings,
            client=client,
            observer=observer,
        )

        if current_review is None or current_review["pass"]:
            logger.info("재작성한 브리핑도 다시 확인했고, 최종 검수를 통과했어요.")
            return rewritten

        followup_issues = (
            "; ".join(current_review["issues"][:3]) or "아직 다듬을 부분이 남아 있어요"
        )
        logger.warning("재작성 뒤에도 보완점이 남아 있어요: %s", followup_issues)
        if not current_review["rewrite_needed"]:
            logger.info("추가 자동 재작성보다는 현재 버전을 유지하는 편이 안전해 보여요.")
            return rewritten

    return rewritten
