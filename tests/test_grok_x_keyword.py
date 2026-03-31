from __future__ import annotations

import morning_brief.data.sources.grok_x_keyword as grok_mod
from morning_brief.data.sources.grok_x_keyword import (
    BITCOIN_CRYPTO_GROUP,
    BITCOIN_CRYPTO_PROMPT,
    GROUP_TOPIC_MAP,
    _bitcoin_crypto_handles,
    fetch_x_keyword_signals,
    search_groups,
)


def test_search_groups_count_and_includes_bitcoin_crypto():
    """Property 3: search_groups가 정확히 3개이고 BITCOIN_CRYPTO_GROUP 포함."""
    assert len(search_groups) == 3
    assert BITCOIN_CRYPTO_GROUP in search_groups


def test_bitcoin_crypto_group_topic_mapping():
    """Property 4: BITCOIN_CRYPTO_GROUP의 topic 매핑이 'bitcoin'."""
    assert GROUP_TOPIC_MAP[BITCOIN_CRYPTO_GROUP] == "bitcoin"


def test_old_group_constants_removed():
    """Property 5: 구 그룹 상수 2개가 모듈에 없음."""
    assert not hasattr(grok_mod, "CRYPTO_ETF_GROUP")
    assert not hasattr(grok_mod, "BTC_ETF_GROUP")


def test_bitcoin_crypto_prompt_contains_required_keywords():
    """Property 6: BITCOIN_CRYPTO_PROMPT에 필수 키워드 포함."""
    assert "ETF" in BITCOIN_CRYPTO_PROMPT
    assert "BTC" in BITCOIN_CRYPTO_PROMPT
    assert "SEC" in BITCOIN_CRYPTO_PROMPT


def test_bitcoin_crypto_handles_union_deduplication():
    """_bitcoin_crypto_handles가 두 그룹 핸들을 중복 없이 병합한다."""
    all_handles = {
        "crypto_and_etf": ["handle_a", "handle_b", "shared"],
        "btc_etf_primary": ["handle_c", "shared"],
    }
    result = _bitcoin_crypto_handles(all_handles)
    assert set(result) == {"handle_a", "handle_b", "shared", "handle_c"}
    assert len(result) == 4  # 중복 제거 확인


def test_bitcoin_crypto_handles_missing_groups():
    """_bitcoin_crypto_handles가 누락된 그룹을 안전하게 처리한다."""
    assert _bitcoin_crypto_handles({}) == []
    assert _bitcoin_crypto_handles({"crypto_and_etf": ["h1"]}) == ["h1"]
    assert _bitcoin_crypto_handles({"btc_etf_primary": ["h2"]}) == ["h2"]


def test_fetch_x_keyword_signals_return_type(monkeypatch):
    """Property 10: fetch_x_keyword_signals 반환 구조가 (list, list, dict) 3-tuple."""
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword.grouped_verified_x_handles",
        lambda: {},
    )
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword._perform_keyword_search",
        lambda **kwargs: ([], {}, []),
    )
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword.execute_with_provider_retry",
        lambda operation, **kwargs: operation(),
    )
    monkeypatch.setattr(
        "morning_brief.data.sources.grok_x_keyword.disabled_reason",
        lambda provider: None,
    )

    result = fetch_x_keyword_signals(api_key="test-key", model="grok-2")
    signals, news_items, keywords = result
    assert isinstance(signals, list)
    assert isinstance(news_items, list)
    assert isinstance(keywords, dict)
