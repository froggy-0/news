"""Property-based tests for tiered collection coverage and skip logic.

**Validates: Requirements 2.1, 2.2, 2.3, 3.2, 3.4, 4.4, 4.5, 4.6**
"""

from __future__ import annotations

import logging
from collections import Counter
from unittest.mock import MagicMock

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

import morning_brief.data.sources.grok_x_keyword as grok_mod
from morning_brief.config import load_settings
from morning_brief.data.news import (
    _cap_signals_by_topic,
    _dedup_x_signals,
    compute_topic_coverage,
    determine_skip_topics,
)
from morning_brief.data.official_signal_registry import load_official_signal_registry
from morning_brief.data.sources.grok_x_keyword import (
    BITCOIN_CRYPTO_GROUP,
    GROUP_TOPIC_MAP,
    MACRO_EQUITY_GROUP,
    fetch_x_keyword_signals,
    search_groups,
)
from morning_brief.models import NewsItem

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

st_news_item = st.builds(
    NewsItem,
    title=st.text(min_size=1),
    url=st.text(min_size=1),
    source=st.text(min_size=1),
    published_at=st.none(),
    topic=st.one_of(st.none(), st.text()),
)

st_coverage_map = st.dictionaries(
    keys=st.text(min_size=1),
    values=st.integers(min_value=0, max_value=10),
)

st_threshold = st.integers(min_value=-1, max_value=10)


# ===========================================================================
# Property 1: Topic coverage 카운트 정확성
# **Validates: Requirements 2.1, 2.2, 2.3**
# ===========================================================================


class TestTopicCoverageProperty:
    """compute_topic_coverage()가 반환하는 카운트가 실제 항목 수와 일치하는지 검증."""

    @given(items=st.lists(st_news_item))
    @settings(max_examples=100)
    def test_each_topic_count_matches_actual(self, items: list[NewsItem]) -> None:
        """각 토픽 카운트가 해당 토픽을 가진 항목 수와 정확히 일치한다."""
        coverage = compute_topic_coverage(items)

        # 유효 토픽만 수동 집계
        expected: Counter[str] = Counter()
        for item in items:
            topic = (item.topic or "").strip()
            if topic:
                expected[topic] += 1

        assert dict(coverage) == dict(expected)

    @given(items=st.lists(st_news_item))
    @settings(max_examples=100)
    def test_none_and_empty_topics_excluded(self, items: list[NewsItem]) -> None:
        """topic이 None이거나 빈 문자열인 항목은 집계에서 제외된다."""
        coverage = compute_topic_coverage(items)

        # coverage 키에 빈 문자열이 없어야 함
        for topic_key in coverage:
            assert topic_key.strip() != ""

    @given(items=st.lists(st_news_item))
    @settings(max_examples=100)
    def test_sum_equals_valid_topic_count(self, items: list[NewsItem]) -> None:
        """모든 카운트 합 == 유효 topic 항목 총 수."""
        coverage = compute_topic_coverage(items)

        valid_count = sum(1 for item in items if (item.topic or "").strip())
        assert sum(coverage.values()) == valid_count


# ===========================================================================
# Property 2: determine_skip_topics 정확성
# **Validates: Requirements 3.2, 3.4, 4.4, 4.5, 4.6**
# ===========================================================================


class TestDetermineSkipTopicsProperty:
    """determine_skip_topics()가 threshold 기준으로 올바른 frozenset을 반환하는지 검증."""

    @given(coverage=st_coverage_map, threshold=st.integers(min_value=-10, max_value=0))
    @settings(max_examples=100)
    def test_threshold_zero_or_negative_returns_empty(
        self, coverage: dict[str, int], threshold: int
    ) -> None:
        """threshold <= 0이면 항상 빈 frozenset을 반환한다."""
        result = determine_skip_topics(coverage, threshold)
        assert result == frozenset()

    @given(coverage=st_coverage_map, threshold=st.integers(min_value=1, max_value=10))
    @settings(max_examples=100)
    def test_included_topics_meet_threshold(self, coverage: dict[str, int], threshold: int) -> None:
        """결과에 포함된 토픽은 count >= threshold, 미포함 토픽은 count < threshold."""
        result = determine_skip_topics(coverage, threshold)

        for topic, count in coverage.items():
            if topic in result:
                assert count >= threshold, (
                    f"topic={topic!r} in result but count={count} < threshold={threshold}"
                )
            else:
                assert count < threshold, (
                    f"topic={topic!r} not in result but count={count} >= threshold={threshold}"
                )


# ===========================================================================
# Task 7.1: Unit tests — compute_topic_coverage, determine_skip_topics, Settings
# **Validates: Requirements 8.3, 8.5**
# ===========================================================================


def _make_news_item(topic: str | None = "macro") -> NewsItem:
    return NewsItem(
        title="Test",
        url="https://example.com",
        source="test",
        published_at=None,
        topic=topic or "",
    )


class TestComputeTopicCoverageUnit:
    def test_compute_topic_coverage_basic(self) -> None:
        items = [
            _make_news_item("bitcoin"),
            _make_news_item("bitcoin"),
            _make_news_item("macro"),
        ]
        coverage = compute_topic_coverage(items)
        assert coverage == {"bitcoin": 2, "macro": 1}

    def test_compute_topic_coverage_none_and_empty(self) -> None:
        items = [
            _make_news_item(None),
            _make_news_item(""),
            _make_news_item("macro"),
        ]
        coverage = compute_topic_coverage(items)
        assert coverage == {"macro": 1}

    def test_compute_topic_coverage_empty_list(self) -> None:
        assert compute_topic_coverage([]) == {}


class TestDetermineSkipTopicsUnit:
    def test_determine_skip_topics_threshold_zero(self) -> None:
        coverage = {"bitcoin": 5, "macro": 3}
        assert determine_skip_topics(coverage, 0) == frozenset()

    def test_determine_skip_topics_basic(self) -> None:
        coverage = {"bitcoin": 3, "macro": 1}
        result = determine_skip_topics(coverage, 2)
        assert result == frozenset({"bitcoin"})


class TestSettingsGrokKeyword:
    def test_settings_grok_keyword_min_official_to_skip_default(self, monkeypatch) -> None:
        monkeypatch.delenv("GROK_KEYWORD_MIN_OFFICIAL_TO_SKIP", raising=False)
        s = load_settings()
        assert s.grok_keyword_min_official_to_skip == 1

    def test_settings_grok_keyword_min_official_to_skip_clamp(self, monkeypatch) -> None:
        # Below minimum → clamped to 0
        monkeypatch.setenv("GROK_KEYWORD_MIN_OFFICIAL_TO_SKIP", "-1")
        s = load_settings()
        assert s.grok_keyword_min_official_to_skip == 0

        # Above maximum → clamped to 5
        monkeypatch.setenv("GROK_KEYWORD_MIN_OFFICIAL_TO_SKIP", "99")
        s = load_settings()
        assert s.grok_keyword_min_official_to_skip == 5


# ===========================================================================
# Task 7.2: Keyword Skip tests
# **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 6.2, 8.1, 8.2, 8.4**
# ===========================================================================


def _patch_grok_keyword(monkeypatch, call_log: list[str] | None = None):
    """Common monkeypatches for fetch_x_keyword_signals tests."""
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword.grouped_verified_x_handles",
        lambda: {"macro_and_equity": ["h1"], "crypto_and_etf": ["h2"], "btc_etf_primary": ["h3"]},
    )

    def fake_search(**kwargs):
        if call_log is not None:
            call_log.append(kwargs.get("group", "unknown"))
        usage = {
            "input_tokens": None,
            "output_tokens": None,
            "cached_input_tokens": None,
            "reasoning_tokens": None,
        }
        return ([], usage, [])

    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword._perform_keyword_search",
        fake_search,
    )
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword.execute_with_provider_retry",
        lambda operation, **kwargs: operation(),
    )
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword.disabled_reason",
        lambda provider: None,
    )


class TestKeywordSkip:
    def test_fetch_x_keyword_signals_skip_bitcoin(self, monkeypatch) -> None:
        call_log: list[str] = []
        _patch_grok_keyword(monkeypatch, call_log)

        fetch_x_keyword_signals(
            api_key="test-key",
            model="grok-2",
            skip_topics=frozenset({"bitcoin"}),
        )
        assert BITCOIN_CRYPTO_GROUP not in call_log
        assert MACRO_EQUITY_GROUP in call_log

    def test_fetch_x_keyword_signals_skip_none_backward_compat(self, monkeypatch) -> None:
        call_log: list[str] = []
        _patch_grok_keyword(monkeypatch, call_log)

        fetch_x_keyword_signals(
            api_key="test-key",
            model="grok-2",
            skip_topics=None,
        )
        # All groups should execute
        assert MACRO_EQUITY_GROUP in call_log
        assert BITCOIN_CRYPTO_GROUP in call_log

    def test_fetch_x_keyword_signals_all_skipped(self, monkeypatch) -> None:
        call_log: list[str] = []
        _patch_grok_keyword(monkeypatch, call_log)

        signals, news, keywords = fetch_x_keyword_signals(
            api_key="test-key",
            model="grok-2",
            skip_topics=frozenset({"macro", "bitcoin"}),
        )
        assert call_log == []
        assert signals == []
        assert news == []
        assert keywords == {}

    def test_skip_log_contains_required_fields(self, monkeypatch, caplog) -> None:
        _patch_grok_keyword(monkeypatch)

        with caplog.at_level(logging.DEBUG, logger="morning_brief.data.sources.grok_x_keyword"):
            fetch_x_keyword_signals(
                api_key="test-key",
                model="grok-2",
                skip_topics=frozenset({"bitcoin"}),
                topic_coverage={"bitcoin": 3},
                coverage_threshold=2,
            )

        skip_records = [
            r
            for r in caplog.records
            if getattr(r, "event", None) == "phase.skip"
            and "official_coverage_sufficient" in str(getattr(r, "attributes", {}))
        ]
        assert len(skip_records) >= 1
        rec = skip_records[0]
        attrs = rec.__dict__.get("attributes", {})
        # provider is extracted to top-level extra by log_structured
        assert getattr(rec, "provider", None) is not None, "Missing field: provider"
        for field in ("reason", "group", "topic", "official_count", "threshold"):
            assert field in attrs, f"Missing field: {field}"
        assert attrs["reason"] == "official_coverage_sufficient"

    def test_observer_log_event_on_skip(self, monkeypatch) -> None:
        _patch_grok_keyword(monkeypatch)
        observer = MagicMock()

        fetch_x_keyword_signals(
            api_key="test-key",
            model="grok-2",
            skip_topics=frozenset({"bitcoin"}),
            topic_coverage={"bitcoin": 3},
            coverage_threshold=2,
            observer=observer,
        )

        observer.log_event.assert_any_call(
            "grok_x_keyword_skipped",
            group=BITCOIN_CRYPTO_GROUP,
            topic="bitcoin",
            official_count=3,
            threshold=2,
        )

    def test_selection_complete_log_includes_skip_counts(self, monkeypatch, caplog) -> None:
        _patch_grok_keyword(monkeypatch)

        with caplog.at_level(logging.DEBUG, logger="morning_brief.data.sources.grok_x_keyword"):
            fetch_x_keyword_signals(
                api_key="test-key",
                model="grok-2",
                skip_topics=frozenset({"bitcoin"}),
            )

        complete_records = [
            r
            for r in caplog.records
            if getattr(r, "event", None) == "selection.complete"
            and "전체 수집" in (r.getMessage() or "")
        ]
        assert len(complete_records) >= 1
        attrs = complete_records[0].__dict__.get("attributes", {})
        assert "executed_groups" in attrs
        assert "skipped_groups" in attrs
        assert attrs["skipped_groups"] >= 1

    def test_xsignal_empty_after_all_skip(self) -> None:
        """_cap_signals_by_topic and _dedup_x_signals handle empty lists correctly."""
        assert _dedup_x_signals([]) == []
        assert _cap_signals_by_topic([], total_max=10, per_topic_max=4) == []

    def test_fetch_x_keyword_signals_integration_skip_with_threshold(
        self, monkeypatch, caplog
    ) -> None:
        """Req 8 AC4: threshold=2, Official bitcoin 2건 → BITCOIN_CRYPTO_GROUP skipped + log reason."""
        call_log: list[str] = []
        _patch_grok_keyword(monkeypatch, call_log)

        with caplog.at_level(logging.DEBUG, logger="morning_brief.data.sources.grok_x_keyword"):
            fetch_x_keyword_signals(
                api_key="test-key",
                model="grok-2",
                skip_topics=frozenset({"bitcoin"}),
                topic_coverage={"bitcoin": 2, "macro": 1},
                coverage_threshold=2,
            )

        assert BITCOIN_CRYPTO_GROUP not in call_log
        assert MACRO_EQUITY_GROUP in call_log
        skip_records = [
            r
            for r in caplog.records
            if getattr(r, "event", None) == "phase.skip"
            and "official_coverage_sufficient" in str(getattr(r, "attributes", {}))
        ]
        assert len(skip_records) >= 1

    def test_fetch_x_keyword_signals_threshold_zero_executes_all(self, monkeypatch) -> None:
        """Req 8 AC5: threshold=0 → all groups execute regardless of coverage."""
        call_log: list[str] = []
        _patch_grok_keyword(monkeypatch, call_log)

        # Even though coverage is high, threshold=0 means skip is disabled
        skip_topics = determine_skip_topics({"bitcoin": 10, "macro": 10}, 0)
        assert skip_topics == frozenset()

        fetch_x_keyword_signals(
            api_key="test-key",
            model="grok-2",
            skip_topics=skip_topics,
        )
        assert MACRO_EQUITY_GROUP in call_log
        assert BITCOIN_CRYPTO_GROUP in call_log


# ===========================================================================
# Task 7.3: ai_bigtech removal verification tests
# **Validates: Requirements 8.6**
# ===========================================================================


class TestAiBigtechRemoval:
    def test_search_groups_no_ai_bigtech(self) -> None:
        assert len(search_groups) == 2
        for group in search_groups:
            assert "ai_bigtech" not in group

    def test_module_no_ai_bigtech_attributes(self) -> None:
        assert not hasattr(grok_mod, "AI_BIGTECH_GROUP")
        assert not hasattr(grok_mod, "AI_BIGTECH_PROMPT")

    def test_registry_no_ai_bigtech_entities(self) -> None:
        registry = load_official_signal_registry()
        entities = registry.get("entities", [])
        ai_bigtech = [e for e in entities if e.get("x_search_group") == "ai_bigtech_primary"]
        assert ai_bigtech == []


# ===========================================================================
# Property 3: Skip된 그룹 API 미호출
# **Validates: Requirements 3.2, 3.4, 3.5, 3.6**
# ===========================================================================


class TestSkipGroupApiProperty:
    @given(skip_topics=st.frozensets(st.sampled_from(["macro", "bitcoin"])))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_skipped_groups_zero_calls_unskipped_one_call(
        self, skip_topics: frozenset[str], monkeypatch
    ) -> None:
        """skip_topics에 포함된 그룹은 API 0회, 미포함 그룹은 1회 호출."""
        call_log: list[str] = []
        _patch_grok_keyword(monkeypatch, call_log)

        fetch_x_keyword_signals(
            api_key="test-key",
            model="grok-2",
            skip_topics=skip_topics,
        )

        for group, topic in GROUP_TOPIC_MAP.items():
            group_calls = call_log.count(group)
            if topic in skip_topics:
                assert group_calls == 0, (
                    f"group={group} topic={topic} should be skipped but got {group_calls} calls"
                )
            else:
                assert group_calls == 1, (
                    f"group={group} topic={topic} should execute once but got {group_calls} calls"
                )


# ===========================================================================
# Property 4: ai_bigtech 그룹 완전 제거 검증
# **Validates: Requirements 1.1, 1.2, 1.3, 1.5**
# ===========================================================================


class TestAiBigtechRemovalProperty:
    def test_no_ai_bigtech_group_attribute(self) -> None:
        assert not hasattr(grok_mod, "AI_BIGTECH_GROUP")

    def test_no_ai_bigtech_prompt_attribute(self) -> None:
        assert not hasattr(grok_mod, "AI_BIGTECH_PROMPT")

    def test_search_groups_exactly_two(self) -> None:
        assert len(search_groups) == 2

    def test_registry_no_ai_bigtech_primary(self) -> None:
        registry = load_official_signal_registry()
        entities = registry.get("entities", [])
        for entity in entities:
            assert entity.get("x_search_group") != "ai_bigtech_primary", (
                f"Found ai_bigtech_primary entity: {entity.get('entity_id')}"
            )
