from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded fallback constants (used when YAML load fails)
# ---------------------------------------------------------------------------

_HARDCODED_PREFERRED_DOMAINS = {
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

_HARDCODED_DOMAIN_SCORES: dict[str, float] = {
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

_HARDCODED_SOURCE_TIERS: dict[str, set[str]] = {
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

# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def _resolve_domain_policy_path() -> Path:
    """CWD와 무관하게 config/domain_policy.yaml 절대 경로를 반환한다."""
    return Path(__file__).parent.parent.parent.parent / "config" / "domain_policy.yaml"


def _parse_domain_policy(
    raw: dict,
) -> tuple[dict[str, float], dict[str, set[str]], set[str]]:
    """YAML raw dict를 파싱해 (domain_scores, source_tiers, preferred_domains) 를 반환한다.

    스키마 오류(음수 score, 필수 필드 누락) 발생 시 ValueError를 raise한다.
    """
    domain_scores: dict[str, float] = {}
    source_tiers: dict[str, set[str]] = {"tier_1": set(), "tier_2": set()}
    preferred_domains: set[str] = set()

    domains = raw.get("domains")
    if not isinstance(domains, list):
        raise ValueError("domains 필드가 list가 아닙니다")

    for entry in domains:
        if not isinstance(entry, dict):
            raise ValueError(f"domains 항목이 dict가 아닙니다: {entry!r}")
        domain = entry.get("domain")
        score = entry.get("score")
        tier = entry.get("tier")

        if not isinstance(domain, str) or not domain.strip():
            raise ValueError(f"domain 필드가 없거나 비어있습니다: {entry!r}")
        if not isinstance(score, (int, float)):
            raise ValueError(f"score 필드가 숫자가 아닙니다: {entry!r}")
        if score < 0:
            raise ValueError(f"score가 음수입니다: {domain}={score}")

        domain = domain.strip()
        domain_scores[domain] = float(score)
        preferred_domains.add(domain)
        if tier in source_tiers:
            source_tiers[tier].add(domain)

    return domain_scores, source_tiers, preferred_domains


def _load_domain_policy() -> tuple[dict[str, float], dict[str, set[str]], set[str]]:
    """YAML에서 도메인 정책을 로드한다.

    YAML 없음 → WARNING + fallback
    파싱 오류 → WARNING + fallback
    성공 → YAML 값 반환
    """
    path = _resolve_domain_policy_path()

    if not path.exists():
        log_structured(
            logger,
            event="domain_policy.fallback",
            message=f"도메인 정책 YAML을 찾을 수 없어 하드코딩된 기본값을 사용합니다: {path}",
            level=logging.WARNING,
            reason="file_not_found",
            path=str(path),
        )
        return _HARDCODED_DOMAIN_SCORES, _HARDCODED_SOURCE_TIERS, _HARDCODED_PREFERRED_DOMAINS

    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("YAML 루트가 dict가 아닙니다")
        domain_scores, source_tiers, preferred_domains = _parse_domain_policy(raw)
    except Exception as exc:
        log_structured(
            logger,
            event="domain_policy.fallback",
            message=f"도메인 정책 YAML 파싱 오류 — 하드코딩된 기본값을 사용합니다: {exc}",
            level=logging.WARNING,
            reason="parse_error",
            error=str(exc),
        )
        return _HARDCODED_DOMAIN_SCORES, _HARDCODED_SOURCE_TIERS, _HARDCODED_PREFERRED_DOMAINS

    return domain_scores, source_tiers, preferred_domains


# 모듈 임포트 시 초기화 (스케줄러 재시작 필요)
DOMAIN_SCORES, SOURCE_TIERS, PREFERRED_DOMAINS = _load_domain_policy()

# ---------------------------------------------------------------------------
# 나머지 상수 (YAML 외부화 대상 아님)
# ---------------------------------------------------------------------------

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
