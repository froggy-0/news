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
    quality = _assess_data_quality(packet=packet, news_packet=[{}, {}, {}, {}])
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
