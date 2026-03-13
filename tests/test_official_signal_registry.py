from __future__ import annotations

import json

from morning_brief.data import official_signal_registry as registry


def _write_registry(tmp_path, entities: list[dict]) -> None:
    registry_file = tmp_path / "official_signal_registry.json"
    registry_file.write_text(json.dumps({"version": 1, "entities": entities}), encoding="utf-8")


def test_checked_in_registry_is_valid():
    registry.load_official_signal_registry.cache_clear()
    assert registry.registry_validation_errors() == []


def test_grouped_verified_x_handles_normalizes_and_limits(monkeypatch, tmp_path):
    entities = [
        {
            "entity_id": f"entity_{index}",
            "entity_name": f"Entity {index}",
            "ticker": "",
            "category": "test",
            "primary_domain": "example.com",
            "newsroom_or_ir_url": "https://example.com/news",
            "x_handle": f"@Handle{index:02d}",
            "x_verified": True,
            "verification_source_url": "https://example.com/verify",
            "verification_method": "official_site",
            "verified_at": "2026-03-13",
            "x_search_group": "alpha",
            "x_search_priority": 20 - index,
            "enabled": True,
            "notes": "",
        }
        for index in range(12)
    ]
    _write_registry(tmp_path, entities)

    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
    registry.load_official_signal_registry.cache_clear()

    handles = registry.grouped_verified_x_handles()

    assert list(handles) == ["alpha"]
    assert len(handles["alpha"]) == registry.MAX_X_HANDLES_PER_GROUP
    assert handles["alpha"][0] == "Handle11"
    assert handles["alpha"][-1] == "Handle02"


def test_registry_validation_errors_for_missing_verified_metadata(monkeypatch, tmp_path):
    entities = [
        {
            "entity_id": "amd",
            "entity_name": "AMD",
            "ticker": "AMD",
            "category": "ai_bigtech_primary",
            "primary_domain": "amd.com",
            "newsroom_or_ir_url": "https://www.amd.com/en/newsroom.html",
            "x_handle": "",
            "x_verified": True,
            "verification_source_url": "",
            "verification_method": "official_newsroom_social_link",
            "verified_at": "2026-03-13",
            "x_search_group": "",
            "x_search_priority": 1,
            "enabled": True,
            "notes": "",
        }
    ]
    _write_registry(tmp_path, entities)

    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
    registry.load_official_signal_registry.cache_clear()

    errors = registry.registry_validation_errors()

    assert "x_verified=true인데 x_handle이 비어 있습니다: amd" in errors
    assert "x_verified=true인데 verification_source_url이 없습니다: amd" in errors
    assert "x_verified=true인데 x_search_group이 없습니다: amd" in errors


def test_registry_validation_errors_when_group_exceeds_limit(monkeypatch, tmp_path):
    entities = [
        {
            "entity_id": f"entity_{index}",
            "entity_name": f"Entity {index}",
            "ticker": "",
            "category": "test",
            "primary_domain": "example.com",
            "newsroom_or_ir_url": "https://example.com/news",
            "x_handle": f"handle{index}",
            "x_verified": True,
            "verification_source_url": "https://example.com/verify",
            "verification_method": "official_site",
            "verified_at": "2026-03-13",
            "x_search_group": "over_limit",
            "x_search_priority": index,
            "enabled": True,
            "notes": "",
        }
        for index in range(11)
    ]
    _write_registry(tmp_path, entities)

    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
    registry.load_official_signal_registry.cache_clear()

    errors = registry.registry_validation_errors()

    assert (
        f"x_search_group over_limit 이(가) {registry.MAX_X_HANDLES_PER_GROUP}개를 초과합니다"
        in errors
    )
