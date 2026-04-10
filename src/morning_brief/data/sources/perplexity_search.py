from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from perplexity import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    Perplexity,
    RateLimitError,
)

from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    execute_with_provider_retry,
    open_circuit,
    parse_retry_after_seconds,
    policy_for,
    record_skip,
)
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import COLLECTED_ITEM_LOG_LIMIT, PipelineObserver

logger = logging.getLogger(__name__)
PERPLEXITY_PROVIDER = "perplexity"
SearchQuery = str | tuple[str, ...]

SEARCH_TIMEOUT_SECONDS = 25
SEARCH_MAX_RESULTS = 8
TOPIC_RESULT_TARGET = 2
TOPIC_RESULT_LIMIT = 8

SOURCE_LABELS = {
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "wsj.com": "WSJ",
    "ft.com": "Financial Times",
    "cnbc.com": "CNBC",
    "marketwatch.com": "MarketWatch",
    "coindesk.com": "CoinDesk",
    "federalreserve.gov": "Federal Reserve",
    "home.treasury.gov": "U.S. Treasury",
    "sec.gov": "SEC",
    "nasdaq.com": "Nasdaq",
    "ishares.com": "iShares",
    "bitbetf.com": "Bitwise",
    "etfs.grayscale.com": "Grayscale",
    "investor.nvidia.com": "NVIDIA IR",
    "news.microsoft.com": "Microsoft",
    "apple.com": "Apple",
    "aboutamazon.com": "Amazon",
    "blog.google": "Google",
    "about.fb.com": "Meta",
    "ir.amd.com": "AMD IR",
    "tsmc.com": "TSMC",
    "asml.com": "ASML",
    "broadcom.com": "Broadcom",
    "prnewswire.com": "PR Newswire",
    "businesswire.com": "Business Wire",
}

TOPIC_IMPACT_LINES = {
    "macro": "금리와 달러, 변동성 흐름을 읽는 데 바로 이어지는 기사예요.",
    "us_equity": "미국 증시 전반의 방향과 시장 폭을 읽는 데 도움이 되는 기사예요.",
    "bitcoin": "비트코인 가격 심리와 ETF 흐름을 이해하는 데 도움이 되는 기사예요.",
}

FT_CONTENT_URL_PREFIX = "https://www.ft.com/content/"
DISALLOWED_MARKET_DATA_DOMAINS = {"markets.ft.com", "data.coindesk.com"}
DISALLOWED_SPONSORED_DOMAINS = {
    "sponsored.bloomberg.com",
    "data.coindesk.com",
    "downloads.coindesk.com",
}

# deny list: API search_domain_filter에 전달 (검색 단계 차단)
SEARCH_DENY_DOMAINS: tuple[str, ...] = (
    "-markets.ft.com",
    "-data.coindesk.com",
    "-downloads.coindesk.com",
    "-sponsored.bloomberg.com",
    "-cn.wsj.com",
    "-jp.reuters.com",
    "-apps.apple.com",
    "-podcasts.apple.com",
    "-tv.apple.com",
    "-status.perplexity.ai",
)

# 파싱 단계에서 차단하는 저품질 소스
LOW_QUALITY_DOMAINS: frozenset[str] = frozenset(
    {
        "reddit.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "linkedin.com",
        "quora.com",
        "medium.com",
        "tradingview.com",
        "investing.com",
        "stockanalysis.com",
        "finance.yahoo.com",
        "wikipedia.org",
        "investopedia.com",
        "glassdoor.com",
        "indeed.com",
    }
)
EXCLUDE_URL_PATTERNS = (
    "/data/equities/tearsheet/",
    "/data/indices/tearsheet/",
    "/data/",
    "/summary?",
    "/summary/",
    "/markets/companies/",
    "/markets/quote/",
    "apps.apple.com",
    "podcasts.apple.com",
    "tv.apple.com",
    "cn.wsj.com",
    "partners.wsj.com",
    "jp.reuters.com",
    "/taxonomy/term/",
    "news.google.com/rss",
    "://status.",
    "statuspage",
)
DISALLOWED_EXACT_URLS = {
    "https://www.sec.gov/newsroom",
    "https://www.sec.gov/newsroom/whats-new",
    "https://www.sec.gov/newsroom/press-releases",
}
EXCLUDE_TITLE_PATTERNS = (
    re.compile(r"markets data\b.*ft\.com$", re.IGNORECASE),
    re.compile(r"\bsummary\s*-\s*ft\.com$", re.IGNORECASE),
    re.compile(r"company announcements", re.IGNORECASE),
    re.compile(r"\bservice status\b", re.IGNORECASE),
    re.compile(r"\bstatus page\b", re.IGNORECASE),
    re.compile(r"\bsystem status\b", re.IGNORECASE),
    re.compile(r"\buptime\b", re.IGNORECASE),
    re.compile(r"^what's new - sec\.gov$", re.IGNORECASE),
    re.compile(r"^newsroom - sec\.gov$", re.IGNORECASE),
    re.compile(r"^press releases - sec\.gov$", re.IGNORECASE),
    re.compile(r"\bpaid program\b", re.IGNORECASE),
    re.compile(r"^home$", re.IGNORECASE),
    re.compile(r"^investment company act notices and orders$", re.IGNORECASE),
    re.compile(r"^edgar filing documents\b", re.IGNORECASE),
)
NON_ENGLISH_TITLE_PATTERN = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MINIMUM_NEWS_TITLE_LENGTH = 10
INTERMEDIATE_LOOKBACK_DAYS = 2
FEDERAL_RESERVE_INDEX_PATHS = {
    "/",
    "/default.htm",
    "/newsevents.htm",
    "/recentpostings.htm",
    "/publications.htm",
    "/releases/h15",
    "/releases/cp",
    "/releases/h41/current",
}
FEDERAL_RESERVE_YEARLY_PRESS_INDEX = re.compile(
    r"^/newsevents/pressreleases/\d{4}-press\.htm$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SearchTopic:
    name: str
    query: SearchQuery
    retry_query: SearchQuery
    recency_filter: str = "day"
    retry_recency_filter: str | None = None


TOPIC_SPECS: tuple[SearchTopic, ...] = (
    SearchTopic(
        name="macro",
        query=(
            "Latest Federal Reserve policy or Treasury yields article published in English. "
            "Prefer Reuters, Bloomberg, WSJ, FT, or CNBC reporting. "
            "Exclude non-English pages, data pages, and quote pages.",
            "Latest US inflation, jobs report, dollar index, or VIX volatility article published in English. "
            "Prefer reliable financial news analysis. "
            "Exclude non-English pages, market data tables, and summary pages.",
            "Latest Treasury yields, rate cut expectations, or risk sentiment article published in English. "
            "Prefer reliable English-language financial reporting. "
            "Exclude non-English pages, data pages, and archive pages.",
        ),
        retry_query=(
            "Federal Reserve policy, Treasury yields, or interest rate outlook article or analysis "
            "published within the last week in English. Prefer reliable financial news reporting. "
            "Exclude non-English pages, data pages, quote pages, and summary pages.",
            "US inflation, employment data, dollar, or market volatility article or analysis "
            "published within the last week in English. Prefer reliable financial reporting. "
            "Exclude non-English pages, data pages, and archive pages.",
            "Treasury yields, rate cut expectations, or risk sentiment weekly review "
            "published within the last week in English. Prefer reliable financial reporting. "
            "Exclude non-English pages, data pages, and summary pages.",
        ),
        retry_recency_filter="week",
    ),
    SearchTopic(
        name="us_equity",
        query=(
            "Latest S&P 500, Nasdaq, or Wall Street market article published in English. "
            "Prefer Reuters, Bloomberg, WSJ, or CNBC reporting. "
            "Exclude non-English pages, stock quote pages, and data tables.",
            "Latest semiconductor stocks, sector rotation, or tech earnings article published in English. "
            "Prefer reliable English-language financial news analysis. "
            "Exclude non-English pages, quote pages, and summary pages.",
            "Latest Dow Jones, futures, or market breadth article published in English. "
            "Prefer reliable English-language financial reporting. "
            "Exclude non-English pages, data pages, and archive pages.",
        ),
        retry_query=(
            "S&P 500, Nasdaq, or Wall Street market sentiment article or weekly review "
            "published within the last week in English. Prefer reliable financial reporting. "
            "Exclude non-English pages, stock quote pages, and data tables.",
            "Semiconductor stocks, sector rotation, or tech earnings article "
            "published within the last week in English. Prefer reliable financial reporting. "
            "Exclude non-English pages, quote pages, and summary pages.",
            "Dow Jones, futures, or risk sentiment article or weekly review "
            "published within the last week in English. Prefer reliable financial reporting. "
            "Exclude non-English pages, data pages, and archive pages.",
        ),
        retry_recency_filter="week",
    ),
    SearchTopic(
        name="bitcoin",
        query=(
            "Latest bitcoin market article published within the last 24 hours on BTC ETF flows, "
            "regulation, institutional demand, or price-moving events. Prefer reliable "
            "English-language reporting and news analysis. Exclude market data pages, ETF product "
            "pages, issuer landing pages, and summary pages."
        ),
        retry_query=(
            "Latest spot bitcoin ETF flow, issuer update, or bitcoin regulation article or "
            "official release published within the last week. Prefer reliable English-language "
            "reporting, regulators, and news analysis. Exclude market data pages, summary pages, "
            "ETF product pages, issuer landing pages, and newsroom listing pages."
        ),
        retry_recency_filter="week",
    ),
)


def _source_label(url: str) -> str:
    domain = normalize_domain(url)
    for candidate, label in SOURCE_LABELS.items():
        if domain_matches(domain, candidate):
            return label
    return domain or "Unknown"


def _normalize_summary(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    if DATE_ONLY_PATTERN.match(raw):
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
        return parsed.replace(hour=12, tzinfo=timezone.utc)

    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _matches_source_filter(url: str, source_filter: str) -> bool:
    normalized_url = str(url or "").strip()
    candidate = str(source_filter or "").strip()
    if not normalized_url or not candidate:
        return False
    if candidate.startswith(("http://", "https://")):
        return normalized_url.lower().startswith(candidate.lower())
    domain = normalize_domain(normalized_url)
    return domain_matches(domain, candidate)


def _is_allowed_domain(url: str, allowed_domains: tuple[str, ...]) -> bool:
    domain = normalize_domain(url)
    if not domain:
        return False
    if not any(_matches_source_filter(url, candidate) for candidate in allowed_domains):
        return False
    if domain_matches(domain, "apple.com"):
        normalized_url = str(url or "").strip().lower()
        return "/newsroom/" in normalized_url
    return True


def _build_client(api_key: str) -> Perplexity:
    return Perplexity(
        api_key=api_key,
        timeout=SEARCH_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _inject_keywords(query: SearchQuery, keywords: list[str] | None) -> SearchQuery:
    """쿼리 끝에 키워드를 주입. 최대 3개까지."""
    if not keywords:
        return query
    suffix = " ".join(keywords[:3])
    if isinstance(query, tuple):
        return tuple(f"{q} {suffix}" for q in query)
    return f"{query} {suffix}"


def _is_weekend() -> bool:
    """토요일(5) 또는 일요일(6)이면 True."""
    return _utc_now().weekday() >= 5


def _usage_field(container: object, *keys: str) -> object | None:
    current = container
    for key in keys:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def _usage_int(container: object, *keys: str) -> int | None:
    value = _usage_field(container, *keys)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_usage_int(container: object, *paths: tuple[str, ...]) -> int | None:
    for path in paths:
        value = _usage_int(container, *path)
        if value is not None:
            return value
    return None


def _usage_snapshot(response: object, payload: dict[str, Any]) -> dict[str, int | None]:
    usage = _usage_container(response, payload)

    return {
        "input_tokens": _first_usage_int(usage, ("prompt_tokens",), ("input_tokens",)),
        "output_tokens": _first_usage_int(usage, ("completion_tokens",), ("output_tokens",)),
        "cached_input_tokens": _first_usage_int(
            usage,
            ("input_tokens_details", "cache_read_input_tokens"),
            ("input_tokens_details", "cache_creation_input_tokens"),
            ("input_tokens_details", "cached_tokens"),
            ("prompt_tokens_details", "cached_tokens"),
        ),
        "reasoning_tokens": _first_usage_int(
            usage,
            ("output_tokens_details", "reasoning_tokens"),
            ("completion_tokens_details", "reasoning_tokens"),
            ("reasoning_tokens",),
        ),
    }


def _usage_container(response: object, payload: dict[str, Any]) -> object | None:
    usage_candidates = (
        _usage_field(response, "usage"),
        _usage_field(response, "model_extra", "usage"),
        _usage_field(response, "__pydantic_extra__", "usage"),
    )
    for usage in usage_candidates:
        if usage is not None:
            return usage
    if isinstance(payload, dict):
        return payload.get("usage")
    return None


def _search_query_value(query: SearchQuery) -> str | list[str]:
    if isinstance(query, tuple):
        queries = [candidate.strip() for candidate in query if candidate.strip()]
        if len(queries) == 1:
            return queries[0]
        return queries
    return str(query).strip()


def _search_query_label(query: SearchQuery) -> str:
    value = _search_query_value(query)
    if isinstance(value, list):
        return " | ".join(value)
    return value


def _search_domain_filter_values(domain_filter: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    for candidate in domain_filter:
        raw = str(candidate or "").strip().lower()
        if not raw:
            continue

        deny = raw.startswith("-")
        body = raw[1:].strip() if deny else raw
        if not body:
            continue

        if body.startswith(".") and "://" not in body and "/" not in body:
            normalized = body
        else:
            # 경로 포함 URL은 도메인 부분만 추출해서 API에 전달
            normalized = normalize_domain(body).removeprefix("www.")
        if not normalized:
            continue

        value = f"-{normalized}" if deny else normalized
        if value in seen:
            continue
        seen.add(value)
        values.append(value)

    return values


def _format_status_error(exc: APIStatusError) -> str:
    status_code = getattr(exc, "status_code", "unknown")
    response = getattr(exc, "response", None)
    detail = ""
    if response is not None:
        try:
            detail = str(response.text).strip()
        except Exception:
            detail = ""
    if detail:
        detail = " ".join(detail.split())[:240]
        return f"status={status_code}, detail={detail}"
    return f"status={status_code}"


def _retry_after_seconds_from_exception(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        return parse_retry_after_seconds(headers.get("Retry-After") or headers.get("retry-after"))
    return None


def _to_http_fetch_error(exc: Exception) -> HttpFetchError:
    if isinstance(exc, RateLimitError):
        message = f"Perplexity Search API 호출 한도에 걸렸어요: {_format_status_error(exc)}"
        open_circuit(PERPLEXITY_PROVIDER, message)
        return HttpFetchError(
            message,
            provider=PERPLEXITY_PROVIDER,
            retryable=False,
            rate_limited=True,
            retry_after_seconds=_retry_after_seconds_from_exception(exc),
        )

    if isinstance(exc, APITimeoutError):
        return HttpFetchError(
            "Perplexity Search API 응답 시간이 너무 오래 걸렸어요.",
            provider=PERPLEXITY_PROVIDER,
            retryable=True,
        )

    if isinstance(exc, APIConnectionError):
        return HttpFetchError(
            "Perplexity Search API 연결을 열지 못했어요.",
            provider=PERPLEXITY_PROVIDER,
            retryable=True,
        )

    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        retry_after_seconds = _retry_after_seconds_from_exception(exc)
        if status_code == 429:
            message = f"Perplexity Search API 호출 한도에 걸렸어요: {_format_status_error(exc)}"
            open_circuit(PERPLEXITY_PROVIDER, message)
            return HttpFetchError(
                message,
                provider=PERPLEXITY_PROVIDER,
                retryable=False,
                rate_limited=True,
                retry_after_seconds=retry_after_seconds,
            )

        return HttpFetchError(
            f"Perplexity Search API가 요청을 거절했어요: {_format_status_error(exc)}",
            provider=PERPLEXITY_PROVIDER,
            retryable=status_code in policy_for(PERPLEXITY_PROVIDER).retryable_statuses,
            rate_limited=status_code == 429,
            retry_after_seconds=retry_after_seconds,
        )

    return HttpFetchError(
        f"Perplexity Search API를 호출하지 못했어요: {exc}",
        provider=PERPLEXITY_PROVIDER,
        retryable=False,
    )


def _search_once(
    *,
    client: Perplexity,
    query: SearchQuery,
    recency_filter: str | None,
    search_after_date_filter: str | None = None,
    search_before_date_filter: str | None = None,
    last_updated_after_filter: str | None = None,
    last_updated_before_filter: str | None = None,
) -> tuple[dict[str, Any], dict[str, int | None], bool]:
    unavailable_reason = disabled_reason(PERPLEXITY_PROVIDER)
    if unavailable_reason:
        record_skip(PERPLEXITY_PROVIDER)
        raise HttpFetchError(
            f"Perplexity는 이번 실행에서 더 이상 쓰지 않을게요: {unavailable_reason}"
        )

    def perform_search() -> tuple[dict[str, Any], dict[str, int | None], bool]:
        try:
            request_kwargs: dict[str, object] = {
                "query": _search_query_value(query),
                "max_results": SEARCH_MAX_RESULTS,
                "search_domain_filter": _search_domain_filter_values(SEARCH_DENY_DOMAINS),
                "search_language_filter": ["en"],
                "country": "US",
            }
            if recency_filter:
                request_kwargs["search_recency_filter"] = recency_filter
            if search_after_date_filter:
                request_kwargs["search_after_date_filter"] = search_after_date_filter
            if search_before_date_filter:
                request_kwargs["search_before_date_filter"] = search_before_date_filter
            if last_updated_after_filter:
                request_kwargs["last_updated_after_filter"] = last_updated_after_filter
            if last_updated_before_filter:
                request_kwargs["last_updated_before_filter"] = last_updated_before_filter

            response = client.search.create(
                **request_kwargs,
            )
        except (RateLimitError, APITimeoutError, APIConnectionError, APIStatusError) as exc:
            raise _to_http_fetch_error(exc) from exc

        try:
            payload = response.model_dump()
        except AttributeError:
            if isinstance(response, dict):
                payload = response
            else:
                raise HttpFetchError(
                    "Perplexity Search API 응답 구조가 예상과 달라요.",
                    provider=PERPLEXITY_PROVIDER,
                )

        if not isinstance(payload, dict):
            raise HttpFetchError(
                "Perplexity Search API 응답 구조가 예상과 달라요.",
                provider=PERPLEXITY_PROVIDER,
            )

        usage_present = _usage_container(response, payload) is not None
        return payload, _usage_snapshot(response, payload), usage_present

    return execute_with_provider_retry(
        provider=PERPLEXITY_PROVIDER,
        operation=perform_search,
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=lambda exc, attempt, max_attempts, delay: log_structured(
            logger,
            event="provider.retry",
            message="Perplexity Search API를 다시 시도하는 중이에요.",
            level=logging.WARNING,
            provider=PERPLEXITY_PROVIDER,
            attempt=attempt,
            max_attempts=max_attempts,
            query=" ".join(_search_query_label(query).split())[:80],
            reason=str(exc),
            retryable=True,
            delay_seconds=delay,
        ),
        retry_after_seconds_for_error=lambda exc: (
            exc.retry_after_seconds if isinstance(exc, HttpFetchError) else None
        ),
    )


def _parse_results(
    *,
    payload: dict[str, Any],
    topic: SearchTopic,
) -> list[NewsItem]:
    items: list[NewsItem] = []
    for raw in _flatten_results(payload)[:TOPIC_RESULT_LIMIT]:
        if not isinstance(raw, dict):
            continue

        title = str(raw.get("title", "")).strip()
        url = str(raw.get("url", "")).strip()
        if (
            not title
            or not url
            or _is_low_quality_source(url)
            or _is_disallowed_market_data_result(title=title, url=url)
            or _is_topic_landing_page(topic=topic.name, url=url, title=title)
            or _is_invalid_news_title(title)
        ):
            continue

        snippet = _normalize_summary(raw.get("snippet"))
        items.append(
            NewsItem(
                title=title,
                url=url,
                source=_source_label(url),
                published_at=_parse_datetime(raw.get("date") or raw.get("last_updated")),
                topic=topic.name,
                provider="perplexity_search",
                summary=snippet,
                why_it_matters=TOPIC_IMPACT_LINES.get(topic.name, ""),
                citations=[url],
            )
        )

    return items


def _is_low_quality_source(url: str) -> bool:
    domain = normalize_domain(url)
    return any(domain_matches(domain, blocked) for blocked in LOW_QUALITY_DOMAINS)


def _is_disallowed_market_data_result(*, title: str, url: str) -> bool:
    normalized_url = str(url or "").strip().lower()
    normalized_title = str(title or "").strip()
    domain = normalize_domain(normalized_url)
    if domain in DISALLOWED_MARKET_DATA_DOMAINS:
        return True
    if domain in DISALLOWED_SPONSORED_DOMAINS:
        return True
    if normalized_url.rstrip("/") in DISALLOWED_EXACT_URLS:
        return True
    if any(part in normalized_url for part in EXCLUDE_URL_PATTERNS):
        return True
    return any(pattern.search(normalized_title) for pattern in EXCLUDE_TITLE_PATTERNS)


def _is_invalid_news_title(title: str) -> bool:
    normalized_title = " ".join(str(title or "").split()).strip()
    if len(normalized_title) < MINIMUM_NEWS_TITLE_LENGTH:
        return True
    return bool(NON_ENGLISH_TITLE_PATTERN.search(normalized_title))


def _search_date_range(days_back: int) -> tuple[str, str]:
    now = _utc_now()
    after_dt = now - timedelta(days=days_back)
    return after_dt.strftime("%m/%d/%Y"), now.strftime("%m/%d/%Y")


def _filter_items_to_date_window(
    items: list[NewsItem],
    *,
    after_filter: str,
    before_filter: str,
) -> list[NewsItem]:
    after_dt = datetime.strptime(after_filter, "%m/%d/%Y").replace(tzinfo=timezone.utc)
    before_dt = datetime.strptime(before_filter, "%m/%d/%Y").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    filtered: list[NewsItem] = []
    for item in items:
        published_at = item.published_at
        if published_at is None:
            filtered.append(item)
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        else:
            published_at = published_at.astimezone(timezone.utc)
        if after_dt <= published_at <= before_dt:
            filtered.append(item)
    return filtered


def _normalized_url_path(url: str) -> str:
    path = urlparse(str(url or "").strip()).path.lower().rstrip("/")
    return path or "/"


def _is_topic_landing_page(*, topic: str, url: str, title: str) -> bool:
    normalized_url = str(url or "").strip().lower()
    normalized_title = " ".join(str(title or "").split()).strip().lower()
    domain = normalize_domain(normalized_url)
    path = _normalized_url_path(normalized_url)

    if topic == "macro" and domain_matches(domain, "federalreserve.gov"):
        if path in FEDERAL_RESERVE_INDEX_PATHS:
            return True
        if FEDERAL_RESERVE_YEARLY_PRESS_INDEX.match(path):
            return True

    if topic == "bitcoin":
        if domain_matches(domain, "sec.gov") and path.startswith("/taxonomy/"):
            return True
        if domain_matches(domain, "sec.gov") and path.startswith("/archives/edgar/data/"):
            return True
        if domain_matches(domain, "ishares.com") and path.startswith("/us/products/"):
            return True
        if domain_matches(domain, "bitbetf.com") and path.startswith("/fund/"):
            return True
        if domain_matches(domain, "etfs.grayscale.com") and path.count("/") <= 1:
            return True
        if domain_matches(domain, "sec.gov") and path in {
            "/",
            "/newsroom",
            "/newsroom/whats-new",
            "/newsroom/press-releases",
        }:
            return True
        if (
            "ethereum trust etf" in normalized_title
            or "blockchain and tech etf" in normalized_title
        ):
            return True

    return False


def _collection_timestamp(item: NewsItem) -> str:
    published_at = item.published_at
    if published_at is not None:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        else:
            published_at = published_at.astimezone(timezone.utc)
        return published_at.isoformat()
    return datetime.now(timezone.utc).isoformat()


def _loggable_perplexity_items(items: list[NewsItem]) -> list[dict[str, str]]:
    return [
        {
            "title": item.title,
            "url": item.url,
            "domain": normalize_domain(item.url).removeprefix("www."),
            "collected_at": _collection_timestamp(item),
        }
        for item in items
    ]


def _loggable_raw_results(results: object) -> list[dict[str, str]]:
    raw_items: list[dict[str, str]] = []
    wrapped = {"results": results}
    for raw in _flatten_results(wrapped)[:COLLECTED_ITEM_LOG_LIMIT]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        url = str(raw.get("url", "")).strip()
        if not title and not url:
            continue
        raw_items.append(
            {
                "title": title,
                "url": url,
                "domain": normalize_domain(url).removeprefix("www."),
            }
        )
    return raw_items


def _flatten_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []

    flattened: list[dict[str, Any]] = []
    for item in results:
        if isinstance(item, dict):
            flattened.append(item)
            continue
        if isinstance(item, list):
            for nested in item:
                if isinstance(nested, dict):
                    flattened.append(nested)
    return flattened


def _fetch_news_from_perplexity(
    *,
    max_items: int,
    api_key: str,
    observer: PipelineObserver | None,
    keywords_by_topic: dict[str, list[str]] | None = None,
) -> list[NewsItem]:
    del max_items

    if not api_key:
        log_structured(
            logger,
            event="phase.skip",
            message="Perplexity API 키가 아직 없어 legacy 뉴스 수집으로 이어갈게요.",
            level=logging.DEBUG,
            provider=PERPLEXITY_PROVIDER,
            reason="missing_api_key",
        )
        return []

    client = _build_client(api_key)
    collected: list[NewsItem] = []

    for topic in TOPIC_SPECS:
        try:
            topic_keywords = (keywords_by_topic or {}).get(topic.name, [])
            topic_items, total_result_count, raw_items = _search_topic_items(
                client=client,
                topic=topic,
                observer=observer,
                keywords=topic_keywords,
            )
            if observer is not None:
                observer.record_perplexity_topic_results(
                    topic.name,
                    [item.url for item in topic_items],
                )
                reason = None
                if not topic_items:
                    reason = "api_empty" if total_result_count == 0 else "filtered_all"
                    if total_result_count > 0:
                        observer.log_event(
                            "perplexity_result_filter_empty",
                            topic=topic.name,
                            raw_result_count=total_result_count,
                            reason="non_article_results",
                        )
                observer.record_perplexity_items_collected(
                    topic=topic.name,
                    items=_loggable_perplexity_items(topic_items),
                    reason=reason,
                    raw_items=raw_items if not topic_items else None,
                )

            log_structured(
                logger,
                event="selection.complete",
                message="Perplexity 토픽 후보를 확인했어요.",
                provider=PERPLEXITY_PROVIDER,
                topic=topic.name,
                candidate_count=total_result_count,
                kept_count=len(topic_items),
            )
            collected.extend(topic_items)
        except HttpFetchError as exc:
            if observer is not None:
                observer.record_perplexity_items_collected(
                    topic=topic.name,
                    items=[],
                    reason="parse_error",
                )
            log_structured(
                logger,
                event="error.raised",
                message="Perplexity 토픽을 확인하는 중 문제가 있었어요.",
                level=logging.WARNING,
                provider=PERPLEXITY_PROVIDER,
                topic=topic.name,
                reason=str(exc),
                error_type=type(exc).__name__,
            )

    return collected


def _search_topic_items(
    *,
    client: Perplexity,
    topic: SearchTopic,
    observer: PipelineObserver | None,
    keywords: list[str] | None = None,
) -> tuple[list[NewsItem], int, list[dict[str, str]]]:
    effective_recency = (
        "week" if _is_weekend() and topic.recency_filter == "day" else topic.recency_filter
    )
    effective_query = _inject_keywords(topic.query, keywords)
    payload, usage, usage_present = _search_once(
        client=client,
        query=effective_query,
        recency_filter=effective_recency,
    )
    first_results = _flatten_results(payload)
    total_result_count = len(first_results)
    raw_items = _loggable_raw_results(first_results)
    _record_perplexity_usage(
        observer=observer,
        query=effective_query,
        usage=usage,
        usage_present=usage_present,
        result_count=total_result_count,
    )
    topic_items = _dedupe_topic_items(_parse_results(payload=payload, topic=topic))
    if len(topic_items) >= TOPIC_RESULT_TARGET or not topic.retry_query:
        return topic_items, total_result_count, raw_items

    # recency 확장 retry (1회)
    retry_recency = topic.retry_recency_filter or topic.recency_filter
    if observer is not None:
        observer.log_event(
            "perplexity_search_widened",
            topic=topic.name,
            stage="recency_retry",
            recency_filter=retry_recency,
            reason="insufficient_recent_results",
        )
    retry_payload, retry_usage, retry_usage_present = _search_once(
        client=client,
        query=topic.retry_query,
        recency_filter=retry_recency,
    )
    retry_results = _flatten_results(retry_payload)
    retry_result_count = len(retry_results)
    raw_items.extend(_loggable_raw_results(retry_results))
    _record_perplexity_usage(
        observer=observer,
        query=topic.retry_query,
        usage=retry_usage,
        usage_present=retry_usage_present,
        result_count=retry_result_count,
    )
    topic_items = _dedupe_topic_items(
        topic_items + _parse_results(payload=retry_payload, topic=topic)
    )
    return topic_items, total_result_count + retry_result_count, raw_items


def _dedupe_topic_items(items: list[NewsItem]) -> list[NewsItem]:
    deduped: dict[tuple[str, str], NewsItem] = {}
    for item in items:
        key = (item.url.strip().lower(), item.title.strip().lower())
        if key not in deduped:
            deduped[key] = item
    return list(deduped.values())


def _record_perplexity_usage(
    *,
    observer: PipelineObserver | None,
    query: SearchQuery,
    usage: dict[str, int | None],
    usage_present: bool,
    result_count: int,
) -> None:
    if observer is None:
        return
    usage_parse_failures = (
        1 if usage_present and all(value is None for value in usage.values()) else 0
    )
    observer.record_provider_usage(
        PERPLEXITY_PROVIDER,
        requests=1,
        response_sources=result_count,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        usage_parse_failures=usage_parse_failures,
    )
    if usage_parse_failures:
        observer.log_event(
            "provider_usage_unparsed",
            provider=PERPLEXITY_PROVIDER,
            query=" ".join(_search_query_label(query).split())[:80],
        )


def fetch_news_from_perplexity(
    *,
    max_items: int,
    api_key: str,
    observer: PipelineObserver | None = None,
    keywords_by_topic: dict[str, list[str]] | None = None,
) -> list[NewsItem]:
    return _fetch_news_from_perplexity(
        max_items=max_items,
        api_key=api_key,
        observer=observer,
        keywords_by_topic=keywords_by_topic,
    )
