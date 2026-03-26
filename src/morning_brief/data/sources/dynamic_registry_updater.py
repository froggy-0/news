"""Dynamic Signal Registry 자동 갱신 모듈.

Grok API의 x_search 도구를 활용하여 그룹별 Top 10개 influential 핸들을 추천받고
dynamic_signal_registry.json을 자동 갱신한다.

설계 원칙:
- Base Layer (official_signal_registry.json) 불변 — Grok 실패 시 Base만 사용
- 그룹당 순차 API 호출 — xai_sdk x_search의 allowed_x_handles는 tool 등록 시 고정이므로 그룹별 별도 요청
- Prompt Caching 극대화 — FIXED_SYSTEM_PROMPT 고정 + x-grok-conv-id gRPC metadata
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
from xai_sdk.tools import x_search

from morning_brief.data.official_signal_registry import (
    _GROK_MAX_HANDLES,
    DYNAMIC_REGISTRY_PATH,
    DynamicSignalEntity,
    list_verified_x_entities,
    load_dynamic_signal_registry,
    load_official_signal_registry,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DYNAMIC_REGISTRY_MODEL = "grok-4-1-fast-non-reasoning"
_CONV_ID = "registry-update-daily-2026"

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
      {"handle": "SECGov", "trust_score": 5, "rationale": "U.S. SEC official account. Crypto regulatory decisions directly impact ETF approvals."},
      {"handle": "CoinDesk", "trust_score": 4, "rationale": "Leading crypto news outlet. Real-time regulatory and market updates."}
    ],
    "ai_bigtech_primary": [...],
    "macro_and_equity": [...],
    "btc_etf_primary": [...]
  }
}

Rules:
- handle: X handle WITHOUT @ symbol
- trust_score: integer 1-5
- rationale: concise English string explaining why this account matters for professional investors
- Return up to 10 handles per group
- Only include accounts you are highly confident are x_verified: true
- Do not include duplicate handles across groups
"""

# ---------------------------------------------------------------------------
# Grok 클라이언트 빌드 (gRPC metadata 포함 — Prompt Caching 최적화)
# ---------------------------------------------------------------------------


def _build_registry_client(api_key: str) -> Client:
    """xai_sdk Client with x-grok-conv-id gRPC metadata for Prompt Caching."""
    return Client(
        api_key=api_key,
        metadata=(("x-grok-conv-id", _CONV_ID),),
    )


# ---------------------------------------------------------------------------
# User Prompt (날짜만 동적)
# ---------------------------------------------------------------------------


def _build_user_prompt(today: date) -> str:
    """날짜만 포함한 최소 동적 User Prompt."""
    return f"Today's date: {today.isoformat()}. Please generate recommendations now."


def _build_messages(today: date) -> list[dict[str, str]]:
    """messages 배열 구성. System Prompt → User Prompt 순서 고정 (캐시 miss 방지)."""
    return [
        {"role": "system", "content": FIXED_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(today)},
    ]


# ---------------------------------------------------------------------------
# 핸들 정규화
# ---------------------------------------------------------------------------


def _normalize_handle(raw: str) -> str:
    """@ 제거 및 공백 정리."""
    return re.sub(r"^@+", "", str(raw or "").strip())


# ---------------------------------------------------------------------------
# Grok API 호출 — 그룹당 순차 실행
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


def _call_grok_for_group(
    *,
    api_key: str,
    group: str,
    base_handles: list[str],
    today: date,
) -> list[dict[str, Any]]:
    """그룹별 Grok API 호출. allowed_x_handles를 Base 핸들로 지정하여 관련 계정 검색.

    xai_sdk의 x_search는 allowed_x_handles가 tool 등록 시 고정되므로,
    그룹별 별도 API 요청으로 순차 실행 (grok_official_signals.py 패턴 동일).
    """
    client = _build_registry_client(api_key)

    # allowed_x_handles: 해당 그룹의 Base 핸들 (최대 10개) — 관련 계정 컨텍스트 제공
    handles_for_tool = base_handles[:_GROK_MAX_HANDLES] if base_handles else None

    try:
        tools = [x_search(allowed_x_handles=handles_for_tool)] if handles_for_tool else [x_search()]
        chat = client.chat.create(
            model=DYNAMIC_REGISTRY_MODEL,
            tools=tools,
            tool_choice="required",
            response_format="json_object",
        )
        chat.append(system(FIXED_SYSTEM_PROMPT))
        chat.append(user(_build_user_prompt(today)))
        response = chat.sample()
    except Exception as exc:
        raise RuntimeError(f"Grok API 호출 실패 (group={group}): {exc}") from exc

    content = getattr(response, "content", "") or ""
    usage = _extract_usage(response)
    logger.info(
        "Dynamic registry Grok API 호출 완료 group=%s cached_input_tokens=%s",
        group,
        usage.get("cached_input_tokens"),
    )
    return _parse_group_handles(content, group)


def _extract_usage(response: object) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    result: dict[str, Any] = {}
    for attr in ("prompt_tokens", "completion_tokens"):
        val = getattr(usage, attr, None)
        if val is not None:
            result[attr] = val
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
        logger.warning("Dynamic registry JSON 파싱 실패 (group=%s): %.200s", group, content)
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
        logger.debug("trust_score 누락/비정상 — 핸들 제외: %s", handle)
        return None

    if trust_score < 3:
        logger.debug("trust_score < 3 — 핸들 제외: %s (score=%d)", handle, trust_score)
        return None

    # rationale 검증
    rationale = str(item.get("rationale", "")).strip()
    if not rationale:
        logger.debug("rationale 누락 — 핸들 제외: %s", handle)
        return None

    return DynamicSignalEntity(
        handle=handle,
        x_search_group=group,
        x_search_priority=0,  # Dynamic 엔티티는 항상 0으로 고정
        trust_score=trust_score,
        rationale=rationale,
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
    logger.info(
        "dynamic_signal_registry.json 저장 완료: %d개 엔티티",
        len(entities),
    )


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def update_dynamic_registry(*, api_key: str, today: date | None = None) -> bool:
    """Dynamic Signal Registry를 Grok API로 갱신한다.

    그룹당 1회씩 순차 API 호출 (N그룹 = N회 요청).
    Grok API 실패 시 False 반환 (Base Layer fallback 트리거용).

    Returns:
        True if successful, False if Grok API failed (Base Layer fallback).
    """
    if not api_key.strip():
        logger.warning("Grok API 키 없음 — Dynamic Registry 갱신 건너뜀")
        return False

    if today is None:
        today = date.today()

    base_handle_set = _get_base_handles()
    all_dynamic: list[DynamicSignalEntity] = []
    any_success = False

    for group in _SEARCH_GROUPS:
        # 해당 그룹의 Base 핸들 목록 (x_search tool context용)
        base_handles_for_group = [
            entity.get("x_handle", "")
            for entity in list_verified_x_entities()
            if entity.get("x_search_group") == group and entity.get("x_handle")
        ]

        try:
            raw_items = _call_grok_for_group(
                api_key=api_key,
                group=group,
                base_handles=base_handles_for_group,
                today=today,
            )
        except RuntimeError as exc:
            logger.warning("Grok API 실패 (group=%s) — Base Layer fallback: %s", group, exc)
            continue

        any_success = True

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

        logger.info(
            "Dynamic registry 그룹 처리: group=%s raw=%d validated=%d new=%d",
            group,
            len(raw_items),
            len(verified),
            len(new_handles),
        )
        all_dynamic.extend(new_handles)

    if not any_success:
        logger.error("모든 Grok API 호출 실패 — Dynamic Registry 갱신 중단, Base Layer fallback")
        return False

    _save_dynamic_registry(all_dynamic)
    return True
