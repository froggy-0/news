from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import logging
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

import feedparser

from morning_brief.config import Settings
from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain
from morning_brief.data.sources.gdelt import fetch_news_from_gdelt
from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.data.sources.perplexity_search import fetch_news_from_perplexity
from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)

PREFERRED_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "coindesk.com",
}

DOMAIN_SCORES = {
    "reuters.com": 5.0,
    "bloomberg.com": 5.0,
    "wsj.com": 4.5,
    "ft.com": 4.5,
    "cnbc.com": 4.0,
    "coindesk.com": 3.8,
}

SOURCE_TIERS = {
    "tier_1": {"reuters.com", "bloomberg.com", "wsj.com", "ft.com"},
    "tier_2": {"cnbc.com", "coindesk.com"},
}

TOPIC_KEYWORDS = {
    "fed": 1.8,
    "fomc": 1.8,
    "treasury": 1.5,
    "yield": 1.5,
    "nasdaq": 1.3,
    "s&p 500": 1.3,
    "semiconductor": 1.5,
    "nvidia": 1.5,
    "microsoft": 1.2,
    "apple": 1.2,
    "amazon": 1.2,
    "google": 1.2,
    "meta": 1.2,
    "amd": 1.2,
    "tsm": 1.3,
    "asml": 1.3,
    "avgo": 1.2,
    "bitcoin": 1.7,
    "btc": 1.6,
    "etf": 1.2,
    "regulation": 1.0,
}

RSS_QUERIES = [
    "Fed interest rates US Treasury yields",
    "US stock market Nasdaq S&P 500 semiconductor",
    "NVIDIA Microsoft Apple Amazon Google Meta AMD TSM ASML AVGO",
    "Bitcoin ETF flows regulation",
]

NEWS_RECENCY_HOURS = 36
MIN_NEWS_ITEMS = 3
FRESH_NEWS_HOURS = 24
MAX_ITEMS_PER_DOMAIN = 2
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"gclid", "fbclid", "ocid", "cmpid", "igshid", "mc_cid", "mc_eid", "ref"}



def _parse_published(entry: dict) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None



def _google_news_rss(query: str) -> str:
    encoded = quote_plus(query)
    return (
        "https://news.google.com/rss/search?"
        f"q={encoded}&hl=en-US&gl=US&ceid=US:en"
    )



def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.netloc:
        return url.strip()

    filtered_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l.startswith(TRACKING_QUERY_PREFIXES):
            continue
        if key_l in TRACKING_QUERY_KEYS:
            continue
        filtered_params.append((key, value))

    filtered_query = urlencode(filtered_params)

    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            filtered_query,
            "",
        )
    )



def _extract_domain(url: str) -> str:
    return normalize_domain(url)



def _is_preferred_domain(url: str) -> bool:
    domain = _extract_domain(url)
    return any(domain_matches(domain, preferred) for preferred in PREFERRED_DOMAINS)



def _recency_score(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.8

    delta = datetime.now(timezone.utc) - published_at
    hours = delta.total_seconds() / 3600
    if hours <= 6:
        return 3.0
    if hours <= 24:
        return 2.0
    if hours <= 48:
        return 1.0
    return 0.2



def _domain_score(url: str) -> float:
    domain = _extract_domain(url)
    best = 0.0
    for preferred_domain, score in DOMAIN_SCORES.items():
        if domain_matches(domain, preferred_domain):
            best = max(best, score)
    return best


def _source_tier(url: str) -> str:
    domain = _extract_domain(url)
    for tier, domains in SOURCE_TIERS.items():
        if any(domain_matches(domain, candidate) for candidate in domains):
            return tier
    if _is_preferred_domain(url):
        return "tier_2"
    return "tier_3"



def _keyword_score(title: str) -> float:
    title_l = title.lower()
    score = 0.0
    for keyword, weight in TOPIC_KEYWORDS.items():
        if keyword in title_l:
            score += weight
    return min(score, 6.0)



def _item_score(item: NewsItem) -> float:
    return _domain_score(item.url) + _recency_score(item.published_at) + _keyword_score(item.title)



def _sort_by_score(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(
        items,
        key=lambda x: (
            _item_score(x),
            x.published_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )



def _apply_domain_diversity_limit(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    selected: list[NewsItem] = []
    per_domain: dict[str, int] = {}

    for item in items:
        domain = _extract_domain(item.url)
        count = per_domain.get(domain, 0)
        if count >= MAX_ITEMS_PER_DOMAIN:
            continue
        selected.append(item)
        per_domain[domain] = count + 1
        if len(selected) >= max_items:
            break

    if len(selected) >= max_items:
        return selected

    for item in items:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= max_items:
            break

    return selected[:max_items]


def _dedup_and_rank(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}

    for item in items:
        title = item.title.strip()
        if not title:
            continue

        normalized_url = _normalize_url(item.url)
        if not normalized_url:
            continue

        source_domain = _extract_domain(normalized_url)
        normalized_item = NewsItem(
            title=title,
            url=normalized_url,
            source=item.source if item.source and item.source != "Unknown" else source_domain,
            published_at=item.published_at,
            topic=item.topic,
            provider=item.provider,
            summary=item.summary,
            why_it_matters=item.why_it_matters,
            citations=list(item.citations),
        )

        key = normalized_url or title.lower()
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = normalized_item
            continue

        if _item_score(normalized_item) > _item_score(existing):
            by_key[key] = normalized_item

    ranked = _sort_by_score(list(by_key.values()))
    return _apply_domain_diversity_limit(ranked, max_items=max_items)



def _collect_from_gdelt(max_items: int, preferred_only: bool = True) -> list[NewsItem]:
    try:
        return fetch_news_from_gdelt(
            topics=list(TOPIC_KEYWORDS.keys()),
            max_items=max_items,
            recency_hours=NEWS_RECENCY_HOURS,
            preferred_domains=PREFERRED_DOMAINS,
            preferred_only=preferred_only,
        )
    except (HttpFetchError, ValueError) as exc:
        logger.warning("GDELT에서 뉴스를 가져오지 못했어요: %s", exc)
        return []



def _collect_from_rss(max_items: int, preferred_only: bool = True) -> list[NewsItem]:
    candidates: list[NewsItem] = []

    for query in RSS_QUERIES:
        feed = feedparser.parse(_google_news_rss(query))
        if getattr(feed, "bozo", 0):
            logger.warning(
                "RSS를 읽는 중 경고가 있었어요. query=%s | %s",
                query,
                getattr(feed, "bozo_exception", "unknown"),
            )

        for entry in feed.entries:
            source = ""
            source_url = ""
            source_data = entry.get("source")
            if isinstance(source_data, dict):
                source = source_data.get("title", "").strip()
                source_url = source_data.get("href", "").strip()

            link = entry.get("link", "").strip() or source_url
            if not link:
                continue

            if preferred_only and not _is_preferred_domain(link):
                continue

            candidates.append(
                NewsItem(
                    title=entry.get("title", "").strip(),
                    url=link,
                    source=source or _extract_domain(link),
                    published_at=_parse_published(entry),
                )
            )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_RECENCY_HOURS)
    filtered = [
        item
        for item in candidates
        if item.published_at is None or item.published_at >= cutoff
    ]

    return _dedup_and_rank(filtered, max_items=max_items)



def _collect_from_newsapi(api_key: str, max_items: int) -> list[NewsItem]:
    if not api_key:
        return []

    payload = get_json_with_retry(
        "https://newsapi.org/v2/everything",
        params={
            "q": "(Fed OR Treasury OR Nasdaq OR S&P 500 OR semiconductor OR Bitcoin ETF OR Nvidia OR Apple OR Microsoft)",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_items * 3,
            "domains": ",".join(sorted(PREFERRED_DOMAINS)),
        },
        headers={"X-Api-Key": api_key},
        timeout=20,
    )

    items: list[NewsItem] = []
    for article in payload.get("articles", []):
        if not isinstance(article, dict):
            continue

        title = str(article.get("title", "")).strip()
        link = str(article.get("url", "")).strip()
        if not title or not link:
            continue

        source = str(article.get("source", {}).get("name", "Unknown")).strip() or "Unknown"

        published_at = None
        published_raw = article.get("publishedAt")
        if isinstance(published_raw, str) and published_raw:
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        items.append(
            NewsItem(
                title=title,
                url=link,
                source=source,
                published_at=published_at,
            )
        )

    return _dedup_and_rank(items, max_items=max_items)



def _merge_rank(items: list[NewsItem], other: list[NewsItem], max_items: int) -> list[NewsItem]:
    return _dedup_and_rank(items + other, max_items=max_items)



def fetch_news(max_items: int, newsapi_key: str = "") -> list[NewsItem]:
    # Collect a wider candidate pool, then rank down to target size.
    candidate_limit = max(max_items * 3, 15)

    items = _collect_from_gdelt(max_items=candidate_limit, preferred_only=True)
    if items:
        logger.info("뉴스 수집은 GDELT 우선 결과를 사용했어요.")

    if len(items) < MIN_NEWS_ITEMS and newsapi_key:
        try:
            newsapi_items = _collect_from_newsapi(newsapi_key, max_items=candidate_limit)
            items = _merge_rank(items, newsapi_items, max_items=candidate_limit)
            if newsapi_items:
                logger.info("뉴스 보강에는 NewsAPI를 함께 사용했어요.")
        except (HttpFetchError, ValueError) as exc:
            logger.warning("NewsAPI에서 뉴스를 가져오지 못했어요: %s", exc)

    if len(items) < MIN_NEWS_ITEMS:
        rss_items = _collect_from_rss(max_items=candidate_limit, preferred_only=True)
        items = _merge_rank(items, rss_items, max_items=candidate_limit)
        if rss_items:
            logger.info("뉴스 보강에는 Google News RSS 우선 도메인을 사용했어요.")

    if len(items) < MIN_NEWS_ITEMS:
        logger.info(
            "우선 신뢰 출처가 %s건이라 범위를 넓혀 GDELT와 RSS를 한 번 더 살펴봤어요.",
            len(items),
        )
        gdelt_broad = _collect_from_gdelt(max_items=candidate_limit, preferred_only=False)
        rss_broad = _collect_from_rss(max_items=candidate_limit, preferred_only=False)
        items = _merge_rank(items, gdelt_broad + rss_broad, max_items=candidate_limit)

    return _dedup_and_rank(items, max_items=max_items)



def summarize_news_quality(items: list[NewsItem]) -> dict:
    domains = {_extract_domain(item.url) for item in items if item.url}
    preferred_count = sum(1 for item in items if _is_preferred_domain(item.url))
    tier_1_count = sum(1 for item in items if _source_tier(item.url) == "tier_1")
    fresh_count = 0

    for item in items:
        if item.published_at is None:
            continue
        age_hours = (datetime.now(timezone.utc) - item.published_at).total_seconds() / 3600
        if age_hours <= FRESH_NEWS_HOURS:
            fresh_count += 1

    return {
        "count": len(items),
        "preferred_count": preferred_count,
        "tier_1_count": tier_1_count,
        "unique_domains": len(domains),
        "fresh_count": fresh_count,
    }


def summarize_news_packet_quality(packet: list[dict]) -> dict:
    count = 0
    preferred_count = 0
    tier_1_count = 0
    fresh_count = 0
    unique_domains: set[str] = set()

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
    }


def packet_item_to_news_item(item: dict) -> NewsItem | None:
    if not isinstance(item, dict):
        return None

    title = str(item.get("title", "")).strip()
    url = str(item.get("url", "")).strip()
    if not title or not url:
        return None

    published_at = None
    published_raw = item.get("published_at")
    if isinstance(published_raw, str) and published_raw.strip():
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    source = str(item.get("source", "")).strip() or _extract_domain(url) or "Unknown"
    return NewsItem(
        title=title,
        url=url,
        source=source,
        published_at=published_at,
        topic=str(item.get("topic", "")).strip(),
        provider=str(item.get("provider", "")).strip(),
        summary=str(item.get("summary", "")).strip(),
        why_it_matters=str(item.get("why_it_matters", "")).strip(),
        citations=[
            str(citation).strip()
            for citation in item.get("citations", [])
            if str(citation).strip()
        ]
        if isinstance(item.get("citations", []), list)
        else [],
    )


def news_items_to_packet(items: list[NewsItem]) -> list[dict]:
    result: list[dict] = []
    now_utc = datetime.now(timezone.utc)

    for item in items:
        age_hours = None
        if item.published_at is not None:
            age_hours = round(
                (now_utc - item.published_at).total_seconds() / 3600,
                2,
            )
        result.append(
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "domain": _extract_domain(item.url),
                "source_tier": _source_tier(item.url),
                "preferred_source": _is_preferred_domain(item.url),
                "age_hours": age_hours,
                "topic": item.topic or None,
                "provider": item.provider or None,
                "summary": item.summary or None,
                "why_it_matters": item.why_it_matters or None,
                "citations": list(item.citations),
            }
        )

    return result


def merge_news_packets(existing_packet: list[dict], extra_items: list[NewsItem], max_items: int) -> list[dict]:
    existing_items = [
        item
        for item in (packet_item_to_news_item(entry) for entry in existing_packet)
        if item is not None
    ]
    merged = _merge_rank(existing_items, extra_items, max_items=max_items)
    return news_items_to_packet(merged)


def build_news_packet(*, settings: Settings) -> list[dict]:
    items: list[NewsItem] = []

    if settings.research_provider == "perplexity":
        items = fetch_news_from_perplexity(
            max_items=settings.max_news_items,
            api_key=settings.perplexity_api_key,
        )
        items = _dedup_and_rank(items, max_items=settings.max_news_items)
        if len(items) < MIN_NEWS_ITEMS and settings.enable_legacy_news_fallback:
            logger.info(
                "Perplexity 후보가 %s건이라 legacy 뉴스 수집으로 빈 부분을 함께 채울게요.",
                len(items),
            )
            legacy_items = fetch_news(
                max_items=settings.max_news_items,
                newsapi_key=settings.newsapi_key,
            )
            items = _merge_rank(items, legacy_items, max_items=settings.max_news_items)
        elif not items:
            logger.warning(
                "Perplexity 연구 결과가 없고 legacy 뉴스 폴백도 꺼져 있어서 빈 뉴스 묶음을 그대로 사용할게요."
            )
    else:
        items = fetch_news(
            max_items=settings.max_news_items,
            newsapi_key=settings.newsapi_key,
        )

    return news_items_to_packet(items)
