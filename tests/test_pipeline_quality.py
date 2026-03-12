from __future__ import annotations

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
