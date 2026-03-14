from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)
PERPLEXITY_PROVIDER = "perplexity"

SEARCH_TIMEOUT_SECONDS = 25
SEARCH_MAX_RESULTS = 5
TOPIC_RESULT_TARGET = 2
TOPIC_RESULT_LIMIT = 5

SOURCE_LABELS = {
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "wsj.com": "WSJ",
    "ft.com": "Financial Times",
    "cnbc.com": "CNBC",
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
    "ai_bigtech": "AI 투자와 빅테크 실적 기대를 해석하는 데 도움이 되는 기사예요.",
    "bitcoin": "비트코인 가격 심리와 ETF 흐름을 이해하는 데 도움이 되는 기사예요.",
}

FT_CONTENT_URL_PREFIX = "https://www.ft.com/content/"
DISALLOWED_MARKET_DATA_DOMAINS = {"markets.ft.com"}
EXCLUDE_URL_PATTERNS = (
    "/data/equities/tearsheet/",
    "/data/indices/tearsheet/",
    "/data/",
    "/summary?",
    "/summary/",
    "podcasts.apple.com",
    "tv.apple.com",
    "cn.wsj.com",
    "jp.reuters.com",
    "news.google.com/rss",
)
EXCLUDE_TITLE_PATTERNS = (
    re.compile(r"markets data\b.*ft\.com$", re.IGNORECASE),
    re.compile(r"\bsummary\s*-\s*ft\.com$", re.IGNORECASE),
    re.compile(r"company announcements", re.IGNORECASE),
)
NON_ENGLISH_TITLE_PATTERN = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
MINIMUM_NEWS_TITLE_LENGTH = 10


@dataclass(frozen=True)
class SearchTopic:
    name: str
    query: str
    retry_query: str
    domain_filter: tuple[str, ...]
    recency_filter: str = "day"


TOPIC_SPECS: tuple[SearchTopic, ...] = (
    SearchTopic(
        name="macro",
        query=(
            "Latest U.S. market-moving macro news article or report published within the last 24 "
            "hours about the Federal Reserve, Treasury yields, dollar, and VIX. Prefer reliable "
            "English-language reporting, news analysis, and official releases only. Exclude "
            "market data pages and summary pages."
        ),
        retry_query=(
            "Latest Federal Reserve or U.S. Treasury or VIX news article or report published "
            "within the last 24 hours affecting U.S. markets. Prefer reliable English-language "
            "reporting, news analysis, and official releases only. Exclude market data pages and "
            "summary pages."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            FT_CONTENT_URL_PREFIX,
            "cnbc.com",
            "federalreserve.gov",
            "home.treasury.gov",
        ),
    ),
    SearchTopic(
        name="us_equity",
        query=(
            "Latest U.S. stock market news article or report published within the last 24 hours "
            "on the S&P 500, Nasdaq, semiconductors, or market breadth. Prefer reliable "
            "English-language reporting, news analysis, and exchange coverage. Exclude market "
            "data pages and summary pages."
        ),
        retry_query=(
            "Latest Nasdaq or S&P 500 or semiconductor sector news article or report published "
            "within the last 24 hours moving the U.S. market. Prefer reliable English-language "
            "reporting and news analysis. Exclude market data pages and summary pages."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            FT_CONTENT_URL_PREFIX,
            "cnbc.com",
            "nasdaq.com",
        ),
    ),
    SearchTopic(
        name="ai_bigtech",
        query=(
            "Latest AI and big tech market-moving news article or report published within the "
            "last 24 hours on Nvidia, Microsoft, Apple, Amazon, Google, Meta, AMD, TSMC, ASML, "
            "or Broadcom. Prefer reliable English-language reporting, news analysis, and company "
            "IR. Exclude market data pages and summary pages."
        ),
        retry_query=(
            "Latest AI infrastructure, data center, semiconductor, or big tech capex news article "
            "or report published within the last 24 hours. Prefer reliable English-language "
            "reporting, news analysis, and company IR. Exclude market data pages and summary "
            "pages."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            FT_CONTENT_URL_PREFIX,
            "cnbc.com",
            "investor.nvidia.com",
            "news.microsoft.com",
            "apple.com",
            "aboutamazon.com",
            "blog.google",
            "about.fb.com",
            "ir.amd.com",
            "tsmc.com",
            "asml.com",
            "broadcom.com",
        ),
    ),
    SearchTopic(
        name="bitcoin",
        query=(
            "Latest bitcoin market news article or report published within the last 24 hours on "
            "BTC ETF flows, regulation, institutional demand, or price-moving events. Prefer "
            "reliable English-language reporting, news analysis, ETF issuers, and regulators. "
            "Exclude market data pages and summary pages."
        ),
        retry_query=(
            "Latest spot bitcoin ETF flow or bitcoin regulation news article or report published "
            "within the last 24 hours. Prefer reliable English-language reporting, news analysis, "
            "and official sources. Exclude market data pages and summary pages."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            FT_CONTENT_URL_PREFIX,
            "cnbc.com",
            "coindesk.com",
            "sec.gov",
            "ishares.com",
            "bitbetf.com",
            "etfs.grayscale.com",
        ),
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
    return any(_matches_source_filter(url, candidate) for candidate in allowed_domains)


def _build_client(api_key: str) -> Perplexity:
    return Perplexity(
        api_key=api_key,
        timeout=SEARCH_TIMEOUT_SECONDS,
        max_retries=1,
    )


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
        "input_tokens": _usage_int(usage, "prompt_tokens"),
        "output_tokens": _usage_int(usage, "completion_tokens"),
        "cached_input_tokens": _first_usage_int(
            usage,
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
    usage = _usage_field(response, "usage")
    if usage is not None:
        return usage
    if isinstance(payload, dict):
        return payload.get("usage")
    return None


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
    query: str,
    domain_filter: tuple[str, ...],
    recency_filter: str,
) -> tuple[dict[str, Any], dict[str, int | None], bool]:
    unavailable_reason = disabled_reason(PERPLEXITY_PROVIDER)
    if unavailable_reason:
        record_skip(PERPLEXITY_PROVIDER)
        raise HttpFetchError(
            f"Perplexity는 이번 실행에서 더 이상 쓰지 않을게요: {unavailable_reason}"
        )

    def perform_search() -> tuple[dict[str, Any], dict[str, int | None], bool]:
        try:
            response = client.search.create(
                query=query,
                max_results=SEARCH_MAX_RESULTS,
                search_domain_filter=list(domain_filter),
                search_recency_filter=recency_filter,
                country="US",
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
        on_retry=lambda exc, attempt, max_attempts, delay: logger.warning(
            "Perplexity Search API를 다시 시도하는 중이에요 (%s/%s). query=%s | %s | sleep=%.2fs",
            attempt,
            max_attempts,
            " ".join(query.split())[:80],
            exc,
            delay,
        ),
        retry_after_seconds_for_error=lambda exc: exc.retry_after_seconds
        if isinstance(exc, HttpFetchError)
        else None,
    )


def _parse_results(*, payload: dict[str, Any], topic: SearchTopic) -> list[NewsItem]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []

    items: list[NewsItem] = []
    for raw in results[:TOPIC_RESULT_LIMIT]:
        if not isinstance(raw, dict):
            continue

        title = str(raw.get("title", "")).strip()
        url = str(raw.get("url", "")).strip()
        if (
            not title
            or not url
            or not _is_allowed_domain(url, topic.domain_filter)
            or _is_disallowed_market_data_result(title=title, url=url)
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


def _is_disallowed_market_data_result(*, title: str, url: str) -> bool:
    normalized_url = str(url or "").strip().lower()
    normalized_title = str(title or "").strip()
    domain = normalize_domain(normalized_url)
    if domain in DISALLOWED_MARKET_DATA_DOMAINS:
        return True
    if any(part in normalized_url for part in EXCLUDE_URL_PATTERNS):
        return True
    return any(pattern.search(normalized_title) for pattern in EXCLUDE_TITLE_PATTERNS)


def _is_invalid_news_title(title: str) -> bool:
    normalized_title = " ".join(str(title or "").split()).strip()
    if len(normalized_title) < MINIMUM_NEWS_TITLE_LENGTH:
        return True
    return bool(NON_ENGLISH_TITLE_PATTERN.search(normalized_title))


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


def _fetch_news_from_perplexity(
    *,
    max_items: int,
    api_key: str,
    observer: PipelineObserver | None,
) -> list[NewsItem]:
    del max_items

    if not api_key:
        logger.info("Perplexity API 키가 아직 없어 legacy 뉴스 수집으로 이어갈게요.")
        return []

    client = _build_client(api_key)
    collected: list[NewsItem] = []

    for topic in TOPIC_SPECS:
        try:
            total_result_count = 0
            payload, usage, usage_present = _search_once(
                client=client,
                query=topic.query,
                domain_filter=topic.domain_filter,
                recency_filter=topic.recency_filter,
            )
            first_results = payload.get("results", [])
            if isinstance(first_results, list):
                total_result_count += len(first_results)
            if observer is not None:
                observer.record_provider_usage(
                    PERPLEXITY_PROVIDER,
                    requests=1,
                    response_sources=len(first_results) if isinstance(first_results, list) else 0,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cached_input_tokens=usage["cached_input_tokens"],
                    reasoning_tokens=usage["reasoning_tokens"],
                    usage_parse_failures=1
                    if usage_present and all(value is None for value in usage.values())
                    else 0,
                )
                if usage_present and all(value is None for value in usage.values()):
                    observer.log_event(
                        "provider_usage_unparsed",
                        provider=PERPLEXITY_PROVIDER,
                        query=" ".join(topic.query.split())[:80],
                    )
            topic_items = _parse_results(payload=payload, topic=topic)
            if len(topic_items) < TOPIC_RESULT_TARGET and topic.retry_query:
                retry_payload, retry_usage, retry_usage_present = _search_once(
                    client=client,
                    query=topic.retry_query,
                    domain_filter=topic.domain_filter,
                    recency_filter=topic.recency_filter,
                )
                retry_results = retry_payload.get("results", [])
                if isinstance(retry_results, list):
                    total_result_count += len(retry_results)
                if observer is not None:
                    observer.record_provider_usage(
                        PERPLEXITY_PROVIDER,
                        requests=1,
                        response_sources=len(retry_results)
                        if isinstance(retry_results, list)
                        else 0,
                        input_tokens=retry_usage["input_tokens"],
                        output_tokens=retry_usage["output_tokens"],
                        cached_input_tokens=retry_usage["cached_input_tokens"],
                        reasoning_tokens=retry_usage["reasoning_tokens"],
                        usage_parse_failures=1
                        if retry_usage_present
                        and all(value is None for value in retry_usage.values())
                        else 0,
                    )
                    if retry_usage_present and all(value is None for value in retry_usage.values()):
                        observer.log_event(
                            "provider_usage_unparsed",
                            provider=PERPLEXITY_PROVIDER,
                            query=" ".join(topic.retry_query.split())[:80],
                        )
                topic_items.extend(_parse_results(payload=retry_payload, topic=topic))
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
                )

            logger.info(
                "Perplexity에서 %s 토픽 후보를 %s건 확인했어요.",
                topic.name,
                len(topic_items),
            )
            collected.extend(topic_items)
        except HttpFetchError as exc:
            if observer is not None:
                observer.record_perplexity_items_collected(
                    topic=topic.name,
                    items=[],
                    reason="parse_error",
                )
            logger.warning(
                "Perplexity에서 %s 토픽을 확인하는 중 문제가 있었어요: %s", topic.name, exc
            )

    return collected


def fetch_news_from_perplexity(
    *,
    max_items: int,
    api_key: str,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    return _fetch_news_from_perplexity(max_items=max_items, api_key=api_key, observer=observer)
