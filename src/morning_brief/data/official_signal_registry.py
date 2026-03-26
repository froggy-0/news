from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

REGISTRY_PATH = Path(__file__).resolve().parent / "registry" / "official_signal_registry.json"
DYNAMIC_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "registry" / "dynamic_signal_registry.json"
)
MAX_X_HANDLES_PER_GROUP = 12
_GROK_MAX_HANDLES = 10


class DynamicSignalEntity(TypedDict):
    handle: str
    x_search_group: str
    x_search_priority: int
    trust_score: int
    rationale: str
    x_verified: bool


class OfficialSignalEntity(TypedDict):
    entity_id: str
    entity_name: str
    ticker: str
    category: str
    primary_domain: str
    newsroom_or_ir_url: str
    x_handle: str
    x_verified: bool
    verification_source_url: str
    verification_method: str
    verified_at: str
    x_search_group: str
    x_search_priority: int
    enabled: bool
    notes: str


def _grouped_verified_x_entries() -> dict[str, list[tuple[int, str]]]:
    grouped: dict[str, list[tuple[int, str]]] = {}
    for entity in list_verified_x_entities():
        group = str(entity.get("x_search_group", "")).strip()
        handle = str(entity.get("x_handle", "")).strip().lstrip("@")
        if not group or not handle:
            continue
        priority = int(entity.get("x_search_priority", 0))
        grouped.setdefault(group, []).append((priority, handle))
    return grouped


@lru_cache(maxsize=1)
def load_official_signal_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_dynamic_signal_registry() -> list[DynamicSignalEntity]:
    """Dynamic Layer를 로드한다. 파일 없으면 빈 리스트 반환 (Base Layer fallback)."""
    if not DYNAMIC_REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(DYNAMIC_REGISTRY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [entity for entity in data if isinstance(entity, dict)]
    except Exception:
        return []


def list_official_signal_entities(*, enabled_only: bool = True) -> list[OfficialSignalEntity]:
    registry = load_official_signal_registry()
    entities = registry.get("entities", [])
    if not isinstance(entities, list):
        return []

    normalized: list[OfficialSignalEntity] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        enabled = bool(entity.get("enabled", True))
        if enabled_only and not enabled:
            continue
        normalized.append(entity)  # type: ignore[arg-type]
    return normalized


def list_verified_x_entities() -> list[OfficialSignalEntity]:
    return [
        entity
        for entity in list_official_signal_entities(enabled_only=True)
        if bool(entity.get("x_verified")) and str(entity.get("x_handle", "")).strip()
    ]


def _dynamic_entity_to_official(entity: DynamicSignalEntity) -> OfficialSignalEntity:
    """DynamicSignalEntity를 OfficialSignalEntity 호환 형식으로 변환한다."""
    handle = str(entity.get("handle", "")).strip().lstrip("@")
    return {  # type: ignore[return-value]
        "entity_id": f"dynamic_{handle.lower()}",
        "entity_name": handle,
        "ticker": "",
        "category": "dynamic",
        "primary_domain": "",
        "newsroom_or_ir_url": "",
        "x_handle": handle,
        "x_verified": True,
        "verification_source_url": "",
        "verification_method": "grok_dynamic",
        "verified_at": "",
        "x_search_group": str(entity.get("x_search_group", "")),
        "x_search_priority": int(entity.get("x_search_priority", 0)),
        "enabled": True,
        "notes": str(entity.get("rationale", "")),
    }


def grouped_verified_x_entities() -> dict[str, list[OfficialSignalEntity]]:
    # Base Layer
    grouped: dict[str, list[OfficialSignalEntity]] = {}
    for entity in list_verified_x_entities():
        group = str(entity.get("x_search_group", "")).strip()
        if not group:
            continue
        grouped.setdefault(group, []).append(entity)

    # Runtime Merge — Dynamic Layer (Base에 없는 신규 핸들만, x_verified=true 이중 확인)
    # dynamic_signal_registry.json 없으면 load_dynamic_signal_registry()가 [] 반환 (fallback)
    base_handles: set[str] = {
        str(e.get("x_handle", "")).strip().lstrip("@").lower()
        for group_list in grouped.values()
        for e in group_list
    }

    for dynamic_entity in load_dynamic_signal_registry():
        if not bool(dynamic_entity.get("x_verified")):
            continue
        handle = str(dynamic_entity.get("handle", "")).strip().lstrip("@")
        if not handle or handle.lower() in base_handles:
            continue
        group = str(dynamic_entity.get("x_search_group", "")).strip()
        if not group:
            continue
        grouped.setdefault(group, []).append(_dynamic_entity_to_official(dynamic_entity))

    # 기존 sort + slice 로직 유지 (변경 없음)
    for group, entities in grouped.items():
        grouped[group] = sorted(
            entities,
            key=lambda entity: (
                int(entity.get("x_search_priority", 0)),
                str(entity.get("entity_id", "")).lower(),
            ),
        )[:MAX_X_HANDLES_PER_GROUP]
    return grouped


def grouped_verified_x_handles() -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for group, entities in grouped_verified_x_entities().items():
        normalized[group] = [
            str(entity.get("x_handle", "")).strip().lstrip("@") for entity in entities
        ]
    return normalized


def registry_validation_errors() -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for entity in list_official_signal_entities(enabled_only=False):
        entity_id = str(entity.get("entity_id", "")).strip()
        if not entity_id:
            errors.append("entity_id가 비어 있는 항목이 있습니다")
            continue
        if entity_id in seen_ids:
            errors.append(f"entity_id가 중복되었습니다: {entity_id}")
        seen_ids.add(entity_id)

        x_verified = bool(entity.get("x_verified"))
        x_handle = str(entity.get("x_handle", "")).strip()
        verification_source_url = str(entity.get("verification_source_url", "")).strip()
        x_group = str(entity.get("x_search_group", "")).strip()
        if x_verified and not x_handle:
            errors.append(f"x_verified=true인데 x_handle이 비어 있습니다: {entity_id}")
        if x_verified and not verification_source_url:
            errors.append(f"x_verified=true인데 verification_source_url이 없습니다: {entity_id}")
        if x_verified and not x_group:
            errors.append(f"x_verified=true인데 x_search_group이 없습니다: {entity_id}")

    for group, handles in _grouped_verified_x_entries().items():
        if len(handles) > MAX_X_HANDLES_PER_GROUP:
            errors.append(f"x_search_group {group} 이(가) {MAX_X_HANDLES_PER_GROUP}개를 초과합니다")

    return errors
