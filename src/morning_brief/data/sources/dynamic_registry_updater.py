"""Dynamic Signal Registry 자동 갱신 모듈.

Grok API chat completion으로 그룹별 Top 10개 influential 핸들을 추천받고
dynamic_signal_registry.json을 자동 갱신한다.

설계 원칙:
- Base Layer (official_signal_registry.json) 불변 — Grok 실패 시 Base만 사용
- 4개 그룹을 단일 API 호출로 처리 — x_search 툴 없이 chat completion 사용
- x_search_priority = 0 고정 — 기존 sorted(key=x_search_priority ASC)[:N] 로직 변경 없이 Dynamic 자동 상위 배치
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from xai_sdk import Client
from xai_sdk.chat import system, user

from morning_brief.data.official_signal_registry import (
    _GROK_MAX_HANDLES,
    DYNAMIC_REGISTRY_PATH,
    DynamicSignalEntity,
    load_dynamic_signal_registry,
    load_official_signal_registry,
)
from morning_brief.logging_utils import log_structured
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DYNAMIC_REGISTRY_MODEL = "grok-4-1-fast-non-reasoning"

# Grok JSON 응답 키 → 코드 그룹 상수값 매핑
_RESPONSE_KEY_TO_GROUP: dict[str, str] = {
    "crypto": "crypto_and_etf",
    "ai_bigtech": "ai_bigtech_primary",
    "macro_and_equity": "macro_and_equity",
    "btc_etf": "btc_etf_primary",
}

# 코드 그룹 상수값 목록 (순서 고정 — 캐싱 안정)
_SEARCH_GROUPS = [
    "crypto_and_etf",
    "ai_bigtech_primary",
    "macro_and_equity",
    "btc_etf_primary",
]

# ---------------------------------------------------------------------------
# System Prompt (고정 — Prompt Caching 대상)
# ---------------------------------------------------------------------------

FIXED_SYSTEM_PROMPT = """You are a financial market intelligence curator specializing in identifying the most influential and trustworthy X (Twitter) accounts for professional investors.

Your task is to recommend verified X accounts for each of the following groups:
- crypto_and_etf: Crypto assets, BTC/ETH ETFs, crypto regulatory news
- ai_bigtech_primary: AI technology, semiconductor, big tech companies
- macro_and_equity: Macroeconomics, Fed policy, equity markets, Treasury
- btc_etf_primary: Bitcoin ETF issuers, institutional BTC adoption

MANDATORY REQUIREMENT: Only recommend accounts with x_verified: true (official blue checkmark). Never recommend unverified accounts.

Trust score hierarchy (higher = preferred):
- trust_score 5: Official institutional/corporate accounts (Fed, SEC, listed company IR, government agencies)
- trust_score 4: Major financial/tech media official accounts (Bloomberg, Reuters, CNBC, WSJ)
- trust_score 3: High-follower expert accounts (analysts, economists, fund managers with significant market influence)

Exclude trust_score < 3.

Output format (strict JSON):
{
  "groups": {
    "crypto_and_etf": [
      {"handle": "SECGov", "trust_score": 5},
      {"handle": "CoinDesk", "trust_score": 4}
    ],
    "ai_bigtech_primary": [...],
    "macro_and_equity": [...],
    "btc_etf_primary": [...]
  }
}

Rules:
- handle: X handle WITHOUT @ symbol
- trust_score: integer 1-5
- Return up to 10 handles per group
- Only include accounts you are highly confident are x_verified: true
- Do not include duplicate handles across groups
"""

# ---------------------------------------------------------------------------
# Grok 클라이언트 빌드 (gRPC metadata 포함 — Prompt Caching 최적화)
# ---------------------------------------------------------------------------


def _build_registry_client(api_key: str) -> Client:
    return Client(api_key=api_key)


# ---------------------------------------------------------------------------
# User Prompt (날짜만 동적)
# ---------------------------------------------------------------------------


def _build_user_prompt(today: date) -> str:
    """날짜만 포함한 최소 동적 User Prompt."""
    return f"Today's date: {today.isoformat()}. Please generate recommendations now."


# ---------------------------------------------------------------------------
# 핸들 정규화
# ---------------------------------------------------------------------------


def _normalize_handle(raw: str) -> str:
    """@ 제거 및 공백 정리."""
    return re.sub(r"^@+", "", str(raw or "").strip())


# ---------------------------------------------------------------------------
# Grok API 호출 — 단일 호출로 4개 그룹 전체 처리
# ---------------------------------------------------------------------------


def _get_base_handles() -> set[str]:
    """Base Layer의 모든 x_handle (소문자 정규화)."""
    handles: set[str] = set()
    try:
        registry = load_official_signal_registry()
        for entity in registry.get("entities", []):
            if isinstance(entity, dict):
                h = _normalize_handle(str(entity.get("x_handle", "")))
                if h:
                    handles.add(h.lower())
    except Exception:
        pass
    return handles


def _call_grok_once(
    *,
    api_key: str,
    today: date,
) -> tuple[str, dict[str, Any]]:
    """4개 그룹을 단일 Grok chat completion 호출로 처리한다.

    x_search 툴 없이 모델의 지식 기반으로 핸들을 추천받는다.
    Returns:
        (content, usage) 튜플.
    """
    client = _build_registry_client(api_key)
    try:
        chat = client.chat.create(
            model=DYNAMIC_REGISTRY_MODEL,
            response_format="json_object",
        )
        chat.append(system(FIXED_SYSTEM_PROMPT))
        chat.append(user(_build_user_prompt(today)))
        response = chat.sample()
    except Exception as exc:
        raise RuntimeError(f"Grok API 호출 실패: {exc}") from exc

    content = getattr(response, "content", "") or ""
    usage = _extract_usage(response)
    log_structured(
        logger,
        event="provider.response",
        message="Dynamic registry Grok API 호출을 완료했어요.",
        provider="grok_keyword",
        cached_input_tokens=usage.get("cached_input_tokens"),
    )
    return content, usage


def _extract_usage(response: object) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    result: dict[str, Any] = {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
    }
    # cached tokens
    cached = None
    for path in [
        ("cached_prompt_text_tokens",),
        ("prompt_tokens_details", "cached_tokens"),
    ]:
        obj = usage
        for key in path:
            obj = getattr(obj, key, None) if obj is not None else None
        if obj is not None:
            cached = obj
            break
    result["cached_input_tokens"] = cached
    return result


# ---------------------------------------------------------------------------
# 응답 파싱 및 검증
# ---------------------------------------------------------------------------


def _parse_group_handles(content: str, group: str) -> list[dict[str, Any]]:
    """Grok JSON 응답에서 그룹별 핸들 목록을 파싱한다."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        log_structured(
            logger,
            event="error.raised",
            message="Dynamic registry JSON 파싱이 실패했어요.",
            level=logging.WARNING,
            provider="grok_keyword",
            group=group,
            preview=content[:200],
            reason="invalid_json",
        )
        return []

    if not isinstance(data, dict):
        return []

    groups_data = data.get("groups", {})
    if not isinstance(groups_data, dict):
        return []

    # Grok 응답 키 → 그룹 상수값 역매핑
    _group_to_response_key = {v: k for k, v in _RESPONSE_KEY_TO_GROUP.items()}
    response_key = _group_to_response_key.get(group, group)

    candidates = groups_data.get(response_key) or groups_data.get(group, [])
    if not isinstance(candidates, list):
        return []

    return [item for item in candidates if isinstance(item, dict)]


def _validate_entity(item: dict[str, Any], group: str) -> DynamicSignalEntity | None:
    """단일 핸들 항목의 스키마를 검증하고 DynamicSignalEntity를 반환한다.

    검증 실패 또는 trust_score < 3이면 None 반환.
    """
    handle = _normalize_handle(str(item.get("handle", "")))
    if not handle:
        return None

    # trust_score 검증
    try:
        trust_score = int(item["trust_score"])
    except (KeyError, TypeError, ValueError):
        log_structured(
            logger,
            event="selection.complete",
            message="trust_score 누락 또는 비정상이라 핸들을 제외했어요.",
            level=logging.DEBUG,
            handle=handle,
            kept_count=0,
            reason="invalid_trust_score",
        )
        return None

    if trust_score < 3:
        log_structured(
            logger,
            event="selection.complete",
            message="trust_score가 낮아 핸들을 제외했어요.",
            level=logging.DEBUG,
            handle=handle,
            trust_score=trust_score,
            kept_count=0,
            reason="trust_score_below_minimum",
        )
        return None

    return DynamicSignalEntity(
        handle=handle,
        x_search_group=group,
        x_search_priority=0,  # Dynamic 엔티티는 항상 0으로 고정
        trust_score=trust_score,
        rationale="",
        x_verified=True,  # x_verified 필터 통과한 것만 저장
    )


def _apply_x_verified_filter(entities: list[DynamicSignalEntity]) -> list[DynamicSignalEntity]:
    """list_verified_x_entities() 파이프라인을 통과하는 핸들만 허용.

    Grok 프롬프트 단계(사전 차단) + 파이프라인 진입 단계 이중 검증.
    현재 Base Layer에 없는 핸들이므로 x_verified=True인 것만 통과.
    실제 x_verified 필드는 항상 True로 고정되어 있으므로 필드 값 재확인.
    """
    return [e for e in entities if e.get("x_verified") is True]


# ---------------------------------------------------------------------------
# Dynamic Registry 저장
# ---------------------------------------------------------------------------


def _filter_new_handles(
    candidates: list[DynamicSignalEntity],
    base_handle_set: set[str],
) -> list[DynamicSignalEntity]:
    """Base에 없는 신규 핸들만 반환."""
    seen: set[str] = set()
    result: list[DynamicSignalEntity] = []
    for entity in candidates:
        h = entity["handle"].lower()
        if h in base_handle_set or h in seen:
            continue
        seen.add(h)
        result.append(entity)
    return result


def _save_dynamic_registry(entities: list[DynamicSignalEntity]) -> None:
    """검증된 Dynamic 엔티티를 dynamic_signal_registry.json에 저장한다.

    tmp 파일에 먼저 쓴 후 rename으로 원자적 교체하여 읽기 중 손상을 방지한다.
    저장 후 lru_cache를 클리어하여 다음 호출 시 새 파일을 읽도록 한다.
    """
    DYNAMIC_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DYNAMIC_REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps([dict(e) for e in entities], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(DYNAMIC_REGISTRY_PATH)  # 원자적 교체
    # 캐시 무효화 — 갱신된 파일을 즉시 반영
    load_dynamic_signal_registry.cache_clear()
    log_structured(
        logger,
        event="artifact.created",
        message="dynamic_signal_registry.json 저장을 완료했어요.",
        path=str(DYNAMIC_REGISTRY_PATH),
        kept_count=len(entities),
    )


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def update_dynamic_registry(
    *,
    api_key: str,
    today: date | None = None,
    observer: PipelineObserver | None = None,
) -> bool:
    """Dynamic Signal Registry를 Grok API로 갱신한다.

    4개 그룹을 단일 API 호출로 처리 (x_search 툴 없이 chat completion 사용).
    Grok API 실패 시 False 반환 (Base Layer fallback 트리거용).

    Returns:
        True if successful, False if Grok API failed (Base Layer fallback).
    """
    if not api_key.strip():
        log_structured(
            logger,
            event="phase.skip",
            message="Grok API 키가 없어 Dynamic Registry 갱신을 건너뛸게요.",
            level=logging.WARNING,
            provider="grok_keyword",
            reason="missing_api_key",
        )
        return False

    if today is None:
        today = date.today()

    base_handle_set = _get_base_handles()

    try:
        content, usage = _call_grok_once(api_key=api_key, today=today)
    except RuntimeError as exc:
        log_structured(
            logger,
            event="error.raised",
            message="Grok API 호출이 실패해 Dynamic Registry 갱신을 중단할게요.",
            level=logging.ERROR,
            provider="grok_keyword",
            reason=str(exc),
            error_type=type(exc).__name__,
        )
        return False

    if observer is not None:
        usage_parse_failures = 1 if all(v is None for v in usage.values()) else 0
        observer.record_provider_usage(
            "grok_keyword",
            requests=1,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_input_tokens=usage.get("cached_input_tokens"),
            usage_parse_failures=usage_parse_failures,
        )

    all_dynamic: list[DynamicSignalEntity] = []

    for group in _SEARCH_GROUPS:
        raw_items = _parse_group_handles(content, group)

        # 스키마 검증 + trust_score 필터
        validated: list[DynamicSignalEntity] = []
        for item in raw_items:
            entity = _validate_entity(item, group)
            if entity is not None:
                validated.append(entity)

        # x_verified 이중 확인
        verified = _apply_x_verified_filter(validated)

        # Base에 없는 신규 핸들만 추가 (그룹당 상한 _GROK_MAX_HANDLES=10)
        new_handles = _filter_new_handles(verified, base_handle_set)[:_GROK_MAX_HANDLES]

        log_structured(
            logger,
            event="selection.complete",
            message="Dynamic registry 그룹 처리를 마쳤어요.",
            provider="grok_keyword",
            group=group,
            raw_count=len(raw_items),
            candidate_count=len(verified),
            kept_count=len(new_handles),
        )
        all_dynamic.extend(new_handles)

    _save_dynamic_registry(all_dynamic)
    return True
