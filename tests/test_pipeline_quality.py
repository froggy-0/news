from __future__ import annotations

from morning_brief.data.data_quality import assess_perplexity_fallback_need
from morning_brief.data.news_rollout import (
    record_news_rollout_run,
    should_reduce_legacy_broad_fallback,
)
from morning_brief.pipeline import _assess_data_quality


def _base_packet(price: float = 10.0) -> dict:
    point = {"price": price, "change_pct": 0.0}
    return {
        "macro": [point.copy(), point.copy(), point.copy(), point.copy()],
        "us_indices": [point.copy(), point.copy(), point.copy()],
        "tech_stocks": [point.copy() for _ in range(10)],
        "bitcoin": {
            "spot": point.copy(),
            "etf_points": [point.copy() for _ in range(5)],
        },
    }


def test_assess_data_quality_ok():
    packet = _base_packet(price=10.0)
    news_packet = [
        {
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "reuters.com",
            "age_hours": 2.0,
        },
        {
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "bloomberg.com",
            "age_hours": 4.0,
        },
        {
            "preferred_source": True,
            "source_tier": "tier_2",
            "domain": "cnbc.com",
            "age_hours": 8.0,
        },
        {
            "preferred_source": True,
            "source_tier": "tier_2",
            "domain": "coindesk.com",
            "age_hours": 10.0,
        },
    ]
    quality = _assess_data_quality(packet=packet, news_packet=news_packet)
    assert quality["status"] == "ok"
    assert quality["zero_price_ratio"] == 0.0


def test_assess_data_quality_degraded_when_zero_ratio_high():
    packet = _base_packet(price=10.0)
    for point in packet["macro"]:
        point["price"] = 0.0
    for point in packet["us_indices"]:
        point["price"] = 0.0
    for i in range(8):
        packet["tech_stocks"][i]["price"] = 0.0
    quality = _assess_data_quality(packet=packet, news_packet=[{}, {}, {}, {}])
    assert quality["status"] == "degraded"
    assert quality["zero_price_ratio"] >= 0.6


def test_assess_data_quality_critical_when_zero_ratio_high():
    packet = _base_packet(price=0.0)
    quality = _assess_data_quality(packet=packet, news_packet=[{}, {}, {}, {}])
    assert quality["status"] == "critical"
    assert quality["zero_price_ratio"] == 1.0


def test_assess_data_quality_degraded_when_news_reliability_is_low():
    packet = _base_packet(price=10.0)
    news_packet = [
        {
            "title": "Market item 1",
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "example-a.com",
            "age_hours": 30.0,
        },
        {
            "title": "Market item 2",
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "example-a.com",
            "age_hours": 28.0,
        },
        {
            "title": "Market item 3",
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "example-b.com",
            "age_hours": 26.0,
        },
    ]

    quality = _assess_data_quality(packet=packet, news_packet=news_packet)

    assert quality["status"] == "degraded"
    assert quality["preferred_news_count"] == 0
    assert quality["tier_1_news_count"] == 0
    assert quality["unique_news_domains"] == 2
    assert quality["fresh_news_count"] == 0


def test_assess_data_quality_accepts_official_signals_as_authoritative_sources():
    packet = _base_packet(price=10.0)
    news_packet = [
        {
            "title": "Macro recap",
            "preferred_source": True,
            "source_tier": "tier_2",
            "domain": "cnbc.com",
            "age_hours": 4.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 돼요.",
            "citations": ["https://www.cnbc.com/macro.html"],
        },
        {
            "title": "AMD official update",
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "x.com",
            "source": "@AMD",
            "age_hours": 2.0,
            "topic": "ai_bigtech",
            "provider": "grok_official_x",
            "official_source": True,
            "why_it_matters": "공식 투자 계획 확인에 직접 참고할 수 있어요.",
            "citations": ["https://x.com/AMD/status/1"],
        },
        {
            "title": "Fidelity official update",
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "x.com",
            "source": "@Fidelity",
            "age_hours": 1.5,
            "topic": "bitcoin",
            "provider": "grok_official_x",
            "official_source": True,
            "why_it_matters": "ETF 수급 해석에 바로 연결할 수 있어요.",
            "citations": ["https://x.com/Fidelity/status/2"],
        },
    ]

    quality = _assess_data_quality(packet=packet, news_packet=news_packet)

    assert quality["status"] == "ok"
    assert quality["official_signal_count"] == 2


def test_assess_data_quality_degraded_when_perplexity_topic_coverage_is_narrow():
    packet = _base_packet(price=10.0)
    news_packet = [
        {
            "title": "Fed item 1",
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "reuters.com",
            "age_hours": 2.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.reuters.com/world/us/fed-item-1"],
        },
        {
            "title": "Fed item 2",
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "bloomberg.com",
            "age_hours": 4.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.bloomberg.com/news/fed-item-2"],
        },
        {
            "title": "Fed item 3",
            "preferred_source": True,
            "source_tier": "tier_2",
            "domain": "cnbc.com",
            "age_hours": 6.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.cnbc.com/fed-item-3.html"],
        },
    ]

    quality = _assess_data_quality(packet=packet, news_packet=news_packet)

    assert quality["status"] == "degraded"
    assert quality["topic_coverage_count"] == 1
    assert quality["perplexity_item_count"] == 3


def test_assess_perplexity_fallback_need_reports_reasons():
    news_packet = [
        {
            "title": "Fed item 1",
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "reuters.com",
            "age_hours": 2.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.reuters.com/world/us/fed-item-1"],
        },
        {
            "title": "Fed item 2",
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "bloomberg.com",
            "age_hours": 3.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.bloomberg.com/news/fed-item-2"],
        },
        {
            "title": "Fed item 3",
            "preferred_source": True,
            "source_tier": "tier_2",
            "domain": "cnbc.com",
            "age_hours": 4.0,
            "topic": "macro",
            "provider": "perplexity_search",
            "why_it_matters": "금리 흐름을 읽는 데 도움이 되는 기사예요.",
            "citations": ["https://www.cnbc.com/fed-item-3.html"],
        },
    ]

    fallback_review = assess_perplexity_fallback_need(news_packet)

    assert fallback_review["needs_legacy_fallback"] is True
    assert fallback_review["topic_coverage_count"] == 1
    assert any("토픽" in reason for reason in fallback_review["reasons"])


def test_rollout_state_requires_three_stable_runs(tmp_path):
    for _ in range(2):
        record_news_rollout_run(
            cache_dir=tmp_path,
            fallback_review={
                "count": 4,
                "unique_domains": 4,
                "topic_coverage_count": 4,
                "fresh_count": 4,
                "citation_backed_count": 4,
                "needs_legacy_fallback": False,
                "reasons": [],
            },
            used_legacy=False,
            allow_broad_fallback=True,
            provider_breakdown={"perplexity_search": 4},
        )

    assert should_reduce_legacy_broad_fallback(tmp_path) is False

    record_news_rollout_run(
        cache_dir=tmp_path,
        fallback_review={
            "count": 4,
            "unique_domains": 4,
            "topic_coverage_count": 4,
            "fresh_count": 4,
            "citation_backed_count": 4,
            "needs_legacy_fallback": False,
            "reasons": [],
        },
        used_legacy=False,
        allow_broad_fallback=True,
        provider_breakdown={"perplexity_search": 4},
    )

    assert should_reduce_legacy_broad_fallback(tmp_path) is True


def test_pipeline_quality_can_improve_after_web_search_backfill(monkeypatch):
    packet = _base_packet(price=10.0)
    weak_news = [
        {
            "title": "Weak item",
            "preferred_source": False,
            "source_tier": "tier_3",
            "domain": "example.com",
            "age_hours": 30.0,
        }
    ]
    initial_quality = _assess_data_quality(packet=packet, news_packet=weak_news)

    improved_news = [
        {
            "title": "Reuters item",
            "url": "https://www.reuters.com/world/us/example",
            "source": "Reuters",
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "reuters.com",
            "age_hours": 2.0,
        },
        {
            "title": "Bloomberg item",
            "url": "https://www.bloomberg.com/news/example",
            "source": "Bloomberg",
            "preferred_source": True,
            "source_tier": "tier_1",
            "domain": "bloomberg.com",
            "age_hours": 3.0,
        },
        {
            "title": "CNBC item",
            "url": "https://www.cnbc.com/example.html",
            "source": "CNBC",
            "preferred_source": True,
            "source_tier": "tier_2",
            "domain": "cnbc.com",
            "age_hours": 4.0,
        },
    ]

    monkeypatch.setattr(
        "morning_brief.pipeline.backfill_news_with_web_search",
        lambda **_: (
            improved_news,
            [{"title": "Reuters", "url": "https://www.reuters.com/world/us/example"}],
        ),
    )

    final_quality = _assess_data_quality(packet=packet, news_packet=improved_news)

    assert initial_quality["status"] == "critical"
    assert final_quality["status"] == "ok"
