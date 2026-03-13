from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

REGISTRY_PATH = Path(__file__).resolve().parent / "registry" / "official_signal_registry.json"
MAX_X_HANDLES_PER_GROUP = 10


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


def grouped_verified_x_handles() -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for group, values in _grouped_verified_x_entries().items():
        handles = [handle for _, handle in sorted(values, key=lambda item: (item[0], item[1].lower()))]
        normalized[group] = handles[:MAX_X_HANDLES_PER_GROUP]
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
