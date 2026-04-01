from __future__ import annotations

from datetime import datetime, timezone

from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain

PREFERRED_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "coindesk.com",
    "federalreserve.gov",
    "home.treasury.gov",
    "sec.gov",
    "ishares.com",
    "bitbetf.com",
    "etfs.grayscale.com",
    "investor.nvidia.com",
    "news.microsoft.com",
    "aboutamazon.com",
    "blog.google",
    "about.fb.com",
    "ir.amd.com",
    "tsmc.com",
    "asml.com",
    "broadcom.com",
    # 확장: 금융·기술·암호화폐
    "apnews.com",
    "barrons.com",
    "marketwatch.com",
    "fortune.com",
    "axios.com",
    "techcrunch.com",
    "theblock.co",
    "cointelegraph.com",
}

DOMAIN_SCORES = {
    "reuters.com": 5.0,
    "bloomberg.com": 5.0,
    "wsj.com": 4.5,
    "ft.com": 4.5,
    "cnbc.com": 4.0,
    "coindesk.com": 3.8,
    "federalreserve.gov": 5.0,
    "home.treasury.gov": 5.0,
    "sec.gov": 5.0,
    "ishares.com": 4.0,
    "bitbetf.com": 4.0,
    "etfs.grayscale.com": 4.0,
    "investor.nvidia.com": 3.9,
    "news.microsoft.com": 3.9,
    "aboutamazon.com": 3.9,
    "blog.google": 3.9,
    "about.fb.com": 3.9,
    "ir.amd.com": 3.9,
    "tsmc.com": 3.8,
    "asml.com": 3.8,
    "broadcom.com": 3.8,
    # 확장 도메인
    "apnews.com": 4.0,
    "barrons.com": 3.8,
    "marketwatch.com": 3.7,
    "fortune.com": 3.5,
    "axios.com": 3.5,
    "techcrunch.com": 3.5,
    "theblock.co": 3.7,
    "cointelegraph.com": 3.5,
}

SOURCE_TIERS = {
    "tier_1": {
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "federalreserve.gov",
        "home.treasury.gov",
        "sec.gov",
    },
    "tier_2": {
        "cnbc.com",
        "coindesk.com",
        "ishares.com",
        "bitbetf.com",
        "etfs.grayscale.com",
        "investor.nvidia.com",
        "news.microsoft.com",
        "aboutamazon.com",
        "blog.google",
        "about.fb.com",
        "ir.amd.com",
        "tsmc.com",
        "asml.com",
        "broadcom.com",
        # 확장 도메인
        "apnews.com",
        "barrons.com",
        "marketwatch.com",
        "fortune.com",
        "axios.com",
        "techcrunch.com",
        "theblock.co",
        "cointelegraph.com",
    },
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


def extract_domain(url: str) -> str:
    return normalize_domain(url)


def is_preferred_domain(url: str) -> bool:
    domain = extract_domain(url)
    return any(domain_matches(domain, preferred) for preferred in PREFERRED_DOMAINS)


def domain_score(url: str) -> float:
    domain = extract_domain(url)
    best = 0.0
    for preferred_domain, score in DOMAIN_SCORES.items():
        if domain_matches(domain, preferred_domain):
            best = max(best, score)
    return best


def source_tier(url: str) -> str:
    domain = extract_domain(url)
    for tier, domains in SOURCE_TIERS.items():
        if any(domain_matches(domain, candidate) for candidate in domains):
            return tier
    if is_preferred_domain(url):
        return "tier_2"
    return "tier_3"


def keyword_score(title: str) -> float:
    title_l = title.lower()
    score = 0.0
    for keyword, weight in TOPIC_KEYWORDS.items():
        if keyword in title_l:
            score += weight
    return min(score, 6.0)


def recency_score(published_at: datetime | None) -> float:
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
