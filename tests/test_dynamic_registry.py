"""Task 10: Hybrid Dynamic Registry 테스트 (10.1 ~ 10.7)

10.1 Merge 로직 단위 테스트
10.2 x_verified 필터 이중 검증 테스트
10.3 Prompt Caching 구조 단위 테스트
10.4 Fallback 동작 통합 테스트
10.5 기존 수집 로직 보존 테스트
10.6 신뢰성 스키마 파싱 테스트
10.7 x_search_priority 정렬 검증 테스트
"""

from __future__ import annotations

import json
from datetime import date

from morning_brief.data import official_signal_registry as registry
from morning_brief.data.sources.dynamic_registry_updater import (
    DYNAMIC_REGISTRY_MODEL,
    FIXED_SYSTEM_PROMPT,
    _apply_x_verified_filter,
    _build_registry_client,
    _build_user_prompt,
    _filter_new_handles,
    _normalize_handle,
    _validate_entity,
    update_dynamic_registry,
)

# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------


def _make_base_entities(count: int, group: str = "alpha") -> list[dict]:
    return [
        {
            "entity_id": f"entity_{i}",
            "entity_name": f"Entity {i}",
            "ticker": "",
            "category": "test",
            "primary_domain": "example.com",
            "newsroom_or_ir_url": "https://example.com/news",
            "x_handle": f"BaseHandle{i:02d}",
            "x_verified": True,
            "verification_source_url": "https://example.com/verify",
            "verification_method": "official_site",
            "verified_at": "2026-03-13",
            "x_search_group": group,
            "x_search_priority": i + 1,
            "enabled": True,
            "notes": "",
        }
        for i in range(count)
    ]


def _write_base_registry(tmp_path, entities: list[dict]) -> None:
    (tmp_path / "official_signal_registry.json").write_text(
        json.dumps({"version": 1, "entities": entities}), encoding="utf-8"
    )


def _write_dynamic_registry(tmp_path, entities: list[dict]) -> None:
    (tmp_path / "dynamic_signal_registry.json").write_text(json.dumps(entities), encoding="utf-8")


# ---------------------------------------------------------------------------
# 10.1 Merge 로직 단위 테스트
# ---------------------------------------------------------------------------


class TestMergeLogic:
    """Property 1 (Base 불변), Property 5 (그룹당 상한) 검증."""

    def test_base_handles_always_included(self, monkeypatch, tmp_path):
        """Base Layer의 핸들은 Dynamic 추가 후에도 항상 포함된다 (Property 1)."""
        base = _make_base_entities(3, "alpha")
        _write_base_registry(tmp_path, base)

        dynamic = [
            {
                "handle": "NewHandle",
                "x_search_group": "alpha",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "new",
                "x_verified": True,
            }
        ]
        _write_dynamic_registry(tmp_path, dynamic)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles()["alpha"]

        # Base handles all present
        for i in range(3):
            assert f"BaseHandle{i:02d}" in handles, f"BaseHandle{i:02d} should be in merged result"
        # Dynamic handle also present
        assert "NewHandle" in handles

    def test_only_new_handles_added_from_dynamic(self, monkeypatch, tmp_path):
        """Grok 추천 핸들 중 Base에 없는 것만 Dynamic Layer로 추가된다."""
        base = _make_base_entities(2, "beta")
        _write_base_registry(tmp_path, base)

        dynamic = [
            # Duplicate of base handle (lowercase mismatch test)
            {
                "handle": "BaseHandle00",
                "x_search_group": "beta",
                "x_search_priority": 0,
                "trust_score": 5,
                "rationale": "duplicate",
                "x_verified": True,
            },
            # New handle
            {
                "handle": "TrulyNewHandle",
                "x_search_group": "beta",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "new",
                "x_verified": True,
            },
        ]
        _write_dynamic_registry(tmp_path, dynamic)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles()["beta"]

        # Duplicate is NOT added twice
        assert handles.count("BaseHandle00") == 1
        # New handle IS added
        assert "TrulyNewHandle" in handles

    def test_group_cap_applied_at_max_handles(self, monkeypatch, tmp_path):
        """그룹당 상한 MAX_X_HANDLES_PER_GROUP 적용 확인 (Property 5)."""
        # 8 base handles (priority 1-8)
        base = _make_base_entities(8, "gamma")
        _write_base_registry(tmp_path, base)

        # 6 dynamic handles (priority 0) — total 14 > 12
        dynamic = [
            {
                "handle": f"DynHandle{i:02d}",
                "x_search_group": "gamma",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": f"dyn {i}",
                "x_verified": True,
            }
            for i in range(6)
        ]
        _write_dynamic_registry(tmp_path, dynamic)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles()["gamma"]

        assert len(handles) == registry.MAX_X_HANDLES_PER_GROUP

    def test_base_low_priority_dropped_when_over_limit(self, monkeypatch, tmp_path):
        """Dynamic+Base 합계가 상한 초과 시 Base 하위 priority 항목 탈락 허용 (Property 5, Req 3.5)."""
        # 12 base handles at priority 1-12
        base = [
            {
                **_make_base_entities(1, "delta")[0],
                "entity_id": f"base_{i}",
                "x_handle": f"BaseHandle{i:02d}",
                "x_search_priority": i + 1,
            }
            for i in range(12)
        ]
        _write_base_registry(tmp_path, base)

        # 2 dynamic handles at priority 0
        dynamic = [
            {
                "handle": f"DynNew{i}",
                "x_search_group": "delta",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "dynamic",
                "x_verified": True,
            }
            for i in range(2)
        ]
        _write_dynamic_registry(tmp_path, dynamic)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles()["delta"]

        # Cap enforced
        assert len(handles) == registry.MAX_X_HANDLES_PER_GROUP

        # Dynamic handles are present (priority=0, highest)
        assert "DynNew0" in handles
        assert "DynNew1" in handles

        # Highest-numbered base handles (priority 11,12) are dropped
        assert "BaseHandle11" not in handles  # priority=12, highest number
        assert "BaseHandle10" not in handles  # priority=11


# ---------------------------------------------------------------------------
# 10.2 x_verified 필터 이중 검증 테스트
# ---------------------------------------------------------------------------


class TestXVerifiedFilter:
    """Property 6: x_verified 이중 검증."""

    def test_unverified_handle_not_in_merged_result(self, monkeypatch, tmp_path):
        """x_verified=false 핸들은 Runtime Merge 단계에서 제외된다."""
        _write_base_registry(tmp_path, [])

        dynamic = [
            {
                "handle": "UnverifiedHandle",
                "x_search_group": "test_group",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "unverified",
                "x_verified": False,
            },
            {
                "handle": "VerifiedHandle",
                "x_search_group": "test_group",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "verified",
                "x_verified": True,
            },
        ]
        _write_dynamic_registry(tmp_path, dynamic)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles().get("test_group", [])

        assert "UnverifiedHandle" not in handles
        assert "VerifiedHandle" in handles

    def test_apply_x_verified_filter_removes_false(self):
        """_apply_x_verified_filter()가 x_verified=false 항목을 제거한다."""
        from morning_brief.data.official_signal_registry import DynamicSignalEntity

        entities = [
            DynamicSignalEntity(
                handle="VerifiedOne",
                x_search_group="g",
                x_search_priority=0,
                trust_score=4,
                rationale="ok",
                x_verified=True,
            ),
            DynamicSignalEntity(
                handle="UnverifiedOne",
                x_search_group="g",
                x_search_priority=0,
                trust_score=4,
                rationale="bad",
                x_verified=False,
            ),
        ]
        result = _apply_x_verified_filter(entities)

        assert len(result) == 1
        assert result[0]["handle"] == "VerifiedOne"

    def test_validate_entity_returns_x_verified_true(self):
        """_validate_entity()가 반환하는 엔티티는 항상 x_verified=True이다."""
        item = {"handle": "SomeHandle", "trust_score": 4, "rationale": "test rationale"}
        entity = _validate_entity(item, "crypto_and_etf")
        assert entity is not None
        assert entity["x_verified"] is True

    def test_unverified_not_in_merged_result_from_dynamic_file(self, monkeypatch, tmp_path):
        """dynamic_signal_registry.json에 x_verified=false가 있어도 Runtime Merge에서 제외된다."""
        _write_base_registry(tmp_path, [])

        # Simulate a dynamic file that somehow has x_verified=false (e.g. manual edit)
        dynamic_with_unverified = [
            {
                "handle": "UnverifiedInFile",
                "x_search_group": "test_group",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "should be filtered",
                "x_verified": False,  # must not appear in merged result
            },
            {
                "handle": "VerifiedInFile",
                "x_search_group": "test_group",
                "x_search_priority": 0,
                "trust_score": 4,
                "rationale": "ok",
                "x_verified": True,
            },
        ]
        _write_dynamic_registry(tmp_path, dynamic_with_unverified)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles().get("test_group", [])
        assert "UnverifiedInFile" not in handles
        assert "VerifiedInFile" in handles


# ---------------------------------------------------------------------------
# 10.3 Prompt Caching 구조 단위 테스트
# ---------------------------------------------------------------------------


class TestPromptCachingStructure:
    """Property 4 (messages 구조)."""

    def test_registry_client_uses_api_key(self, monkeypatch):
        """_build_registry_client()는 api_key만으로 Client를 생성한다."""
        captured_kwargs = {}

        class MockClient:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

        monkeypatch.setattr(
            "morning_brief.data.sources.dynamic_registry_updater.Client", MockClient
        )
        _build_registry_client("my-api-key")

        assert captured_kwargs.get("api_key") == "my-api-key"

    def test_user_prompt_contains_only_date_as_dynamic_info(self):
        """User Prompt에는 날짜 외 동적 정보가 최소화된다 (Property 4)."""
        today = date(2026, 3, 26)
        prompt = _build_user_prompt(today)
        assert today.isoformat() in prompt
        # System prompt content is NOT duplicated in user prompt
        assert "trust_score 5" not in prompt
        assert "x_verified: true" not in prompt

    def test_system_prompt_does_not_contain_date(self):
        """FIXED_SYSTEM_PROMPT에는 날짜 정보가 없다 (캐싱 안정성)."""
        assert "2026" not in FIXED_SYSTEM_PROMPT
        assert "2025" not in FIXED_SYSTEM_PROMPT

    def test_model_is_grok_fast_non_reasoning(self):
        """모델이 grok-4-1-fast-non-reasoning으로 고정되어 있다."""
        assert DYNAMIC_REGISTRY_MODEL == "grok-4-1-fast-non-reasoning"


# ---------------------------------------------------------------------------
# 10.4 Fallback 동작 통합 테스트
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    """Property 2: Grok API 장애 시 Base Layer fallback."""

    def test_no_dynamic_file_returns_base_only(self, monkeypatch, tmp_path):
        """dynamic_signal_registry.json 없으면 Base만 반환 (Property 2, 8)."""
        base = _make_base_entities(3, "fallback_group")
        _write_base_registry(tmp_path, base)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry,
            "DYNAMIC_REGISTRY_PATH",
            tmp_path / "nonexistent_dynamic_registry.json",
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles()

        assert "fallback_group" in handles
        assert len(handles["fallback_group"]) == 3
        for i in range(3):
            assert f"BaseHandle{i:02d}" in handles["fallback_group"]

    def test_grok_api_failure_returns_false_and_uses_base(self, monkeypatch, tmp_path):
        """Grok API 호출 실패 시 update_dynamic_registry()가 False를 반환한다 (Property 2)."""
        import morning_brief.data.sources.dynamic_registry_updater as upd

        def mock_call_fail(**kwargs):
            raise RuntimeError("Grok API 다운")

        monkeypatch.setattr(upd, "_call_grok_once", mock_call_fail)
        monkeypatch.setattr(
            registry,
            "REGISTRY_PATH",
            tmp_path / "official_signal_registry.json",
        )
        (tmp_path / "official_signal_registry.json").write_text(
            json.dumps({"version": 1, "entities": []}), encoding="utf-8"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        result = update_dynamic_registry(api_key="test-key", today=date(2026, 3, 26))

        assert result is False

    def test_bad_json_for_group_returns_empty_group(self, monkeypatch, tmp_path):
        """응답 JSON에 그룹 키가 없으면 해당 그룹은 빈 리스트로 처리되고 다른 그룹은 정상 저장."""
        import json as _json

        import morning_brief.data.sources.dynamic_registry_updater as upd

        saved_data = []

        # crypto_and_etf 그룹만 포함된 응답 (나머지 그룹 키 없음)
        content = _json.dumps(
            {
                "groups": {
                    "crypto": [{"handle": "CryptoHandle", "trust_score": 4}],
                }
            }
        )

        def mock_call_once(**kwargs):
            return content, {}

        def mock_save(entities):
            saved_data.extend(entities)

        monkeypatch.setattr(upd, "_call_grok_once", mock_call_once)
        monkeypatch.setattr(upd, "_save_dynamic_registry", mock_save)
        (tmp_path / "official_signal_registry.json").write_text(
            json.dumps({"version": 1, "entities": []}), encoding="utf-8"
        )
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        result = update_dynamic_registry(api_key="test-key", today=date(2026, 3, 26))

        assert result is True
        # crypto_and_etf 그룹 매핑("crypto" 키)으로 핸들 1개 저장
        assert any(e["x_search_group"] == "crypto_and_etf" for e in saved_data)


# ---------------------------------------------------------------------------
# 10.5 기존 수집 로직 보존 테스트
# ---------------------------------------------------------------------------


class TestExistingLogicPreservation:
    """Property 8: 기존 채널 데이터 수집 로직 그대로 유지."""

    def test_runtime_merge_result_identical_to_base_when_no_dynamic(self, monkeypatch, tmp_path):
        """dynamic_signal_registry.json 없을 때 기존 수집 결과와 동일하다 (Property 8)."""
        base = _make_base_entities(5, "preservation_group")
        _write_base_registry(tmp_path, base)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry,
            "DYNAMIC_REGISTRY_PATH",
            tmp_path / "no_dynamic.json",
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        handles = registry.grouped_verified_x_handles().get("preservation_group", [])
        expected = [f"BaseHandle{i:02d}" for i in range(5)]

        # All base handles present and in correct priority order
        assert handles == expected

    def test_no_or_query_pattern_in_codebase(self):
        """OR 쿼리(from:handle OR ...) 코드가 존재하지 않는다 (Property 8)."""
        import re
        from pathlib import Path

        src_dir = Path(__file__).parent.parent / "src"
        or_pattern = re.compile(r"from:\w+\s+OR\s+from:", re.IGNORECASE)

        violations = []
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            if or_pattern.search(content):
                violations.append(str(py_file))

        assert not violations, f"OR query found in: {violations}"

    def test_grouped_verified_x_handles_returns_string_list(self, monkeypatch, tmp_path):
        """grouped_verified_x_handles()는 문자열 리스트를 반환한다."""
        base = _make_base_entities(2, "string_group")
        _write_base_registry(tmp_path, base)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "no_dynamic.json")
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        result = registry.grouped_verified_x_handles()
        for group, handles in result.items():
            assert isinstance(handles, list)
            for h in handles:
                assert isinstance(h, str)
                assert not h.startswith("@"), f"Handle should not start with @: {h}"


# ---------------------------------------------------------------------------
# 10.6 신뢰성 스키마 파싱 테스트
# ---------------------------------------------------------------------------


class TestTrustScoreParsing:
    """Property 9: trust_score 스키마 검증."""

    def test_trust_score_below_3_excluded(self):
        """trust_score < 3인 항목은 Dynamic Registry에서 제외된다 (Property 9)."""
        for score in [1, 2]:
            item = {"handle": "LowTrustHandle", "trust_score": score}
            assert _validate_entity(item, "crypto_and_etf") is None, (
                f"trust_score={score} should be excluded"
            )

    def test_trust_score_3_and_above_included(self):
        """trust_score >= 3인 항목은 포함된다."""
        for score in [3, 4, 5]:
            item = {"handle": f"Handle{score}", "trust_score": score}
            entity = _validate_entity(item, "crypto_and_etf")
            assert entity is not None, f"trust_score={score} should be included"
            assert entity["trust_score"] == score

    def test_missing_trust_score_excluded(self):
        """trust_score 필드 누락 시 해당 핸들은 저장되지 않는다."""
        item = {"handle": "NoScore"}
        assert _validate_entity(item, "crypto_and_etf") is None

    def test_missing_rationale_accepted(self):
        """rationale 필드 없어도 핸들은 저장된다 (rationale은 필수 아님)."""
        item = {"handle": "NoRationale", "trust_score": 4}
        entity = _validate_entity(item, "crypto_and_etf")
        assert entity is not None
        assert entity["rationale"] == ""

    def test_rationale_stored_as_empty_string(self):
        """rationale이 없으면 빈 문자열로 저장된다."""
        item = {"handle": "AnyHandle", "trust_score": 4}
        entity = _validate_entity(item, "crypto_and_etf")
        assert entity is not None
        assert entity["rationale"] == ""

    def test_valid_entity_has_all_required_fields(self):
        """유효한 엔티티는 6개 필드를 모두 포함한다."""
        item = {"handle": "ValidHandle", "trust_score": 4}
        entity = _validate_entity(item, "crypto_and_etf")
        assert entity is not None
        for field in (
            "handle",
            "x_search_group",
            "x_search_priority",
            "trust_score",
            "rationale",
            "x_verified",
        ):
            assert field in entity, f"Missing field: {field}"

    def test_handle_normalized(self):
        """@ 접두사가 제거된다."""
        item = {"handle": "@AtHandle", "trust_score": 4}
        entity = _validate_entity(item, "crypto_and_etf")
        assert entity is not None
        assert entity["handle"] == "AtHandle"

    def test_normalize_handle_strips_at(self):
        """_normalize_handle()이 @ 제거한다."""
        assert _normalize_handle("@Hello") == "Hello"
        assert _normalize_handle("@@Double") == "Double"
        assert _normalize_handle("NoAt") == "NoAt"
        assert _normalize_handle("  spaced  ") == "spaced"


# ---------------------------------------------------------------------------
# 10.7 x_search_priority 정렬 검증 테스트
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    """Property 7: Dynamic 엔티티 x_search_priority=0, 정렬 최우선."""

    def test_dynamic_entity_priority_is_zero(self):
        """Dynamic 엔티티의 x_search_priority는 항상 0이다 (Property 7)."""
        item = {"handle": "TestHandle", "trust_score": 4}
        entity = _validate_entity(item, "crypto_and_etf")
        assert entity is not None
        assert entity["x_search_priority"] == 0

    def test_dynamic_entities_sorted_before_base(self, monkeypatch, tmp_path):
        """Dynamic 엔티티(priority=0)가 Base 엔티티(priority>=1)보다 앞에 배치된다 (Property 7)."""
        base = _make_base_entities(3, "sort_group")  # priority 1, 2, 3
        _write_base_registry(tmp_path, base)

        dynamic = [
            {
                "handle": "DynamicFirst",
                "x_search_group": "sort_group",
                "x_search_priority": 0,
                "trust_score": 3,
                "rationale": "dynamic entity",
                "x_verified": True,
            }
        ]
        _write_dynamic_registry(tmp_path, dynamic)

        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        monkeypatch.setattr(
            registry, "DYNAMIC_REGISTRY_PATH", tmp_path / "dynamic_signal_registry.json"
        )
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        entities = registry.grouped_verified_x_entities()["sort_group"]

        # Dynamic entity is first
        assert entities[0]["x_search_priority"] == 0
        assert entities[0].get("x_handle") == "DynamicFirst"

        # Base entities follow
        for e in entities[1:]:
            assert int(e.get("x_search_priority", 0)) >= 1

    def test_filter_new_handles_excludes_base_duplicates(self):
        """_filter_new_handles()가 Base에 이미 있는 핸들을 제외한다."""
        from morning_brief.data.official_signal_registry import DynamicSignalEntity

        base_handles = {"basehandle", "existingone"}
        candidates = [
            DynamicSignalEntity(
                handle="BaseHandle",
                x_search_group="g",
                x_search_priority=0,
                trust_score=4,
                rationale="dup",
                x_verified=True,
            ),
            DynamicSignalEntity(
                handle="TrulyNew",
                x_search_group="g",
                x_search_priority=0,
                trust_score=4,
                rationale="new",
                x_verified=True,
            ),
        ]
        result = _filter_new_handles(candidates, base_handles)

        handles = [e["handle"] for e in result]
        assert "BaseHandle" not in handles
        assert "TrulyNew" in handles

    def test_grok_max_handles_cap_in_save(self, monkeypatch, tmp_path):
        """Dynamic Registry 저장 시 그룹당 _GROK_MAX_HANDLES=10 상한 적용."""
        import json as _json

        import morning_brief.data.sources.dynamic_registry_updater as upd

        saved_data = []

        # 각 그룹에 15개 핸들을 반환하는 mock
        groups_content = {
            "crypto": [{"handle": f"Crypto{i:02d}", "trust_score": 4} for i in range(15)],
            "macro_and_equity": [{"handle": f"Macro{i:02d}", "trust_score": 4} for i in range(15)],
            "btc_etf": [{"handle": f"BTC{i:02d}", "trust_score": 4} for i in range(15)],
        }
        mock_content = _json.dumps({"groups": groups_content})

        def mock_call_once(**kwargs):
            return mock_content, {}

        def mock_save(entities):
            saved_data.extend(entities)

        monkeypatch.setattr(upd, "_call_grok_once", mock_call_once)
        monkeypatch.setattr(upd, "_save_dynamic_registry", mock_save)
        (tmp_path / "official_signal_registry.json").write_text(
            json.dumps({"version": 1, "entities": []}), encoding="utf-8"
        )
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "official_signal_registry.json")
        registry.load_official_signal_registry.cache_clear()
        registry.load_dynamic_signal_registry.cache_clear()

        update_dynamic_registry(api_key="test-key", today=date(2026, 3, 26))

        # Each of the 4 groups should have at most _GROK_MAX_HANDLES handles
        from collections import Counter

        from morning_brief.data.official_signal_registry import _GROK_MAX_HANDLES

        group_counts = Counter(e["x_search_group"] for e in saved_data)
        for group, count in group_counts.items():
            assert count <= _GROK_MAX_HANDLES, (
                f"Group {group} has {count} > {_GROK_MAX_HANDLES} handles"
            )
