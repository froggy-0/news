from __future__ import annotations

from morning_brief.data.news_policy import FRESH_NEWS_HOURS

MIN_NEWS_ITEMS = 3
MIN_PREFERRED_NEWS_ITEMS = 2
MIN_TIER_1_NEWS_ITEMS = 1
MIN_UNIQUE_NEWS_DOMAINS = 3
MIN_FRESH_NEWS_ITEMS = 2
MIN_TOPIC_COVERAGE = 2
PERPLEXITY_PROVIDER = "perplexity_search"


def _safe_price(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def summarize_news_packet_quality(packet: list[dict]) -> dict:
    count = 0
    preferred_count = 0
    tier_1_count = 0
    fresh_count = 0
    citation_backed_count = 0
    explained_count = 0
    perplexity_item_count = 0
    unique_domains: set[str] = set()
    unique_topics: set[str] = set()

    for item in packet:
        if not isinstance(item, dict):
            continue

        count += 1

        if bool(item.get("preferred_source")):
            preferred_count += 1

        if str(item.get("source_tier", "")).strip().lower() == "tier_1":
            tier_1_count += 1

        domain = str(item.get("domain", "")).strip().lower()
        if domain:
            unique_domains.add(domain)

        topic = str(item.get("topic", "")).strip().lower()
        if topic:
            unique_topics.add(topic)

        provider = str(item.get("provider", "")).strip().lower()
        if provider == PERPLEXITY_PROVIDER:
            perplexity_item_count += 1

        citations = item.get("citations", [])
        if isinstance(citations, list) and any(str(value).strip() for value in citations):
            citation_backed_count += 1

        if str(item.get("why_it_matters", "")).strip():
            explained_count += 1

        age_hours = item.get("age_hours")
        try:
            if age_hours is not None and float(age_hours) <= FRESH_NEWS_HOURS:
                fresh_count += 1
        except (TypeError, ValueError):
            continue

    return {
        "count": count,
        "preferred_count": preferred_count,
        "tier_1_count": tier_1_count,
        "unique_domains": len(unique_domains),
        "fresh_count": fresh_count,
        "topic_coverage_count": len(unique_topics),
        "citation_backed_count": citation_backed_count,
        "explained_count": explained_count,
        "perplexity_item_count": perplexity_item_count,
    }


def _build_perplexity_fallback_reasons(summary: dict) -> list[str]:
    reasons: list[str] = []
    if summary["count"] < MIN_NEWS_ITEMS:
        reasons.append(f"기사 수가 {summary['count']}건이라 아직 적어요")
    if summary["fresh_count"] < MIN_FRESH_NEWS_ITEMS:
        reasons.append(f"최신 기사 수가 {summary['fresh_count']}건이라 조금 부족해요")
    if summary["unique_domains"] < MIN_UNIQUE_NEWS_DOMAINS:
        reasons.append(f"도메인이 {summary['unique_domains']}개라 출처가 아직 좁아요")
    if summary["topic_coverage_count"] < MIN_TOPIC_COVERAGE:
        reasons.append(f"토픽이 {summary['topic_coverage_count']}개라 주제가 조금 좁아요")
    if summary["citation_backed_count"] < summary["count"]:
        reasons.append("일부 기사에 근거 링크가 빠져 있어요")
    return reasons


def _append_perplexity_quality_warnings(warnings: list[str], news_quality: dict) -> None:
    if news_quality["perplexity_item_count"] <= 0:
        return
    if news_quality["topic_coverage_count"] < MIN_TOPIC_COVERAGE:
        warnings.append(
            f"Perplexity 기준 토픽 커버리지가 {news_quality['topic_coverage_count']}개라 조금 좁습니다"
        )
    if news_quality["citation_backed_count"] < news_quality["perplexity_item_count"]:
        warnings.append("Perplexity 결과 일부에 근거 링크가 부족합니다")
    if news_quality["explained_count"] < news_quality["perplexity_item_count"]:
        warnings.append("Perplexity 결과 일부에 시장 해석 메모가 빠져 있습니다")


def assess_perplexity_fallback_need(news_packet: list[dict]) -> dict:
    summary = summarize_news_packet_quality(news_packet)
    reasons = _build_perplexity_fallback_reasons(summary)

    return {
        **summary,
        "needs_legacy_fallback": bool(reasons),
        "reasons": reasons,
    }


def assess_data_quality(packet: dict, news_packet: list[dict]) -> dict:
    macro = packet.get("macro", [])
    us_indices = packet.get("us_indices", [])
    tech_stocks = packet.get("tech_stocks", [])
    btc = packet.get("bitcoin", {})

    numeric_points = macro + us_indices + tech_stocks + btc.get("etf_points", []) + [btc.get("spot", {})]
    zero_points = [
        p for p in numeric_points if isinstance(p, dict) and _safe_price(p.get("price", 0.0)) <= 0.0
    ]

    zero_ratio = (len(zero_points) / len(numeric_points)) if numeric_points else 1.0
    news_quality = summarize_news_packet_quality(news_packet)

    warnings: list[str] = []
    if zero_ratio >= 0.6:
        warnings.append(f"가격 데이터의 {zero_ratio*100:.0f}%가 폴백 값입니다")
    if news_quality["count"] < MIN_NEWS_ITEMS:
        warnings.append(
            f"핵심 뉴스가 {news_quality['count']}건으로 최소 기준({MIN_NEWS_ITEMS}건) 미달입니다"
        )
    if news_quality["count"] >= MIN_NEWS_ITEMS and news_quality["preferred_count"] < MIN_PREFERRED_NEWS_ITEMS:
        warnings.append(
            f"우선 신뢰 출처 뉴스가 {news_quality['preferred_count']}건으로 충분하지 않습니다"
        )
    if news_quality["count"] >= MIN_NEWS_ITEMS and news_quality["tier_1_count"] < MIN_TIER_1_NEWS_ITEMS:
        warnings.append("최상위 신뢰 출처(Reuters/Bloomberg/WSJ/FT) 기사가 없습니다")
    if news_quality["count"] >= MIN_NEWS_ITEMS and news_quality["unique_domains"] < MIN_UNIQUE_NEWS_DOMAINS:
        warnings.append(
            f"뉴스 출처 다양성이 낮습니다({news_quality['unique_domains']}개 도메인)"
        )
    if news_quality["count"] >= MIN_NEWS_ITEMS and news_quality["fresh_count"] < MIN_FRESH_NEWS_ITEMS:
        warnings.append(f"24시간 내 최신 뉴스가 {news_quality['fresh_count']}건으로 부족합니다")
    _append_perplexity_quality_warnings(warnings, news_quality)

    if news_quality["count"] < MIN_NEWS_ITEMS or zero_ratio >= 0.8:
        status = "critical"
    elif warnings:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "zero_price_ratio": round(zero_ratio, 4),
        "warnings": warnings,
        "news_count": news_quality["count"],
        "preferred_news_count": news_quality["preferred_count"],
        "tier_1_news_count": news_quality["tier_1_count"],
        "unique_news_domains": news_quality["unique_domains"],
        "fresh_news_count": news_quality["fresh_count"],
        "topic_coverage_count": news_quality["topic_coverage_count"],
        "citation_backed_count": news_quality["citation_backed_count"],
        "explained_count": news_quality["explained_count"],
        "perplexity_item_count": news_quality["perplexity_item_count"],
    }
