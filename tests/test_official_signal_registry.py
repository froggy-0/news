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
    count = registry.MAX_X_HANDLES_PER_GROUP + 2  # exceed limit by 2
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
        for index in range(count)
    ]
    _write_registry(tmp_path, entities)

    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
    registry.load_official_signal_registry.cache_clear()

    handles = registry.grouped_verified_x_handles()

    assert list(handles) == ["alpha"]
    assert len(handles["alpha"]) == registry.MAX_X_HANDLES_PER_GROUP
    # Sorted by priority (ascending), then entity_id; highest priority = lowest number
    assert handles["alpha"][0] == f"Handle{count - 1:02d}"
    assert handles["alpha"][-1] == f"Handle{count - registry.MAX_X_HANDLES_PER_GROUP:02d}"


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
    count = registry.MAX_X_HANDLES_PER_GROUP + 1  # exceed limit by 1
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
        for index in range(count)
    ]
    _write_registry(tmp_path, entities)

    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
    registry.load_official_signal_registry.cache_clear()

    errors = registry.registry_validation_errors()

    assert (
        f"x_search_group over_limit 이(가) {registry.MAX_X_HANDLES_PER_GROUP}개를 초과합니다"
        in errors
    )


# ---------------------------------------------------------------------------
# Task 3.1: Verify new entities exist with correct attributes
# ---------------------------------------------------------------------------

_NEW_CRYPTO_AND_ETF = [
    ("vaneck", "vaneck_us", "crypto_and_etf", 2),
    ("franklin_templeton", "FTI_US", "crypto_and_etf", 2),
    ("invesco", "InvescoUS", "crypto_and_etf", 2),
]

_NEW_MACRO_AND_EQUITY = [
    ("white_house", "WhiteHouse", "macro_and_equity", 1),
    ("potus", "POTUS", "macro_and_equity", 1),
]

_ALL_NEW_ENTITIES = _NEW_CRYPTO_AND_ETF + _NEW_MACRO_AND_EQUITY


def test_new_entity_ids_exist_in_registry():
    """All 9 new entity_ids are present in the registry."""
    registry.load_official_signal_registry.cache_clear()
    entities = registry.list_official_signal_entities(enabled_only=False)
    entity_ids = {e["entity_id"] for e in entities}

    expected_ids = {eid for eid, _, _, _ in _ALL_NEW_ENTITIES}
    assert expected_ids.issubset(entity_ids), f"Missing entity_ids: {expected_ids - entity_ids}"


def test_new_entities_verified_enabled_and_group():
    """Each new entity has x_verified=true, enabled=true, correct group and priority."""
    registry.load_official_signal_registry.cache_clear()
    entities = registry.list_official_signal_entities(enabled_only=False)
    by_id = {e["entity_id"]: e for e in entities}

    for entity_id, x_handle, expected_group, expected_priority in _ALL_NEW_ENTITIES:
        entity = by_id[entity_id]
        assert entity["x_verified"] is True, f"{entity_id}: x_verified should be True"
        assert entity["enabled"] is True, f"{entity_id}: enabled should be True"
        assert entity["x_search_group"] == expected_group, (
            f"{entity_id}: expected group {expected_group}, got {entity['x_search_group']}"
        )
        assert entity["x_search_priority"] == expected_priority, (
            f"{entity_id}: expected priority {expected_priority}, got {entity['x_search_priority']}"
        )


# ---------------------------------------------------------------------------
# Task 3.2: Group handle counts and MAX constant
# ---------------------------------------------------------------------------


def test_grouped_handle_counts():
    """Verify handle counts per group after expansion."""
    registry.load_official_signal_registry.cache_clear()
    handles = registry.grouped_verified_x_handles()

    assert "ai_bigtech_primary" not in handles
    assert len(handles["crypto_and_etf"]) == 10
    assert len(handles["macro_and_equity"]) == 11


def test_max_x_handles_per_group_constant():
    assert registry.MAX_X_HANDLES_PER_GROUP == 12


# ---------------------------------------------------------------------------
# Task 3.3: Existing handle preservation
# ---------------------------------------------------------------------------

_ORIGINAL_25_ENTITY_IDS = [
    "federal_reserve",
    "us_treasury",
    "sec",
    "fidelity",
    "blackrock_ishares",
    "apple",
    "tsmc",
    "bitwise",
    "grayscale",
    "ark_21shares",
    "walter_bloomberg",
    "first_squawk",
    "bloomberg_markets",
    "nick_timiraos",
    "lisa_abramowicz",
    "dan_ives",
    "eric_balchunas",
    "nate_geraci",
    "coindesk",
    "cnbc",
]


def test_original_entities_still_present():
    """Original entities (excluding removed ai_bigtech) remain in the registry."""
    registry.load_official_signal_registry.cache_clear()
    entities = registry.list_official_signal_entities(enabled_only=False)
    entity_ids = {e["entity_id"] for e in entities}

    missing = [eid for eid in _ORIGINAL_25_ENTITY_IDS if eid not in entity_ids]
    assert missing == [], f"Original entities missing from registry: {missing}"
