from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from perplexity import APIConnectionError, APIStatusError, APITimeoutError, Perplexity, RateLimitError

from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)

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
            "Latest U.S. market-moving macro news about Federal Reserve, Treasury yields, "
            "dollar, and VIX. Prefer reliable reporting and official releases only."
        ),
        retry_query=(
            "Latest Federal Reserve or U.S. Treasury or VIX news affecting U.S. markets today. "
            "Prefer reliable reporting and official releases only."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            "ft.com",
            "cnbc.com",
            "federalreserve.gov",
            "home.treasury.gov",
        ),
    ),
    SearchTopic(
        name="us_equity",
        query=(
            "Latest U.S. stock market news on S&P 500, Nasdaq, semiconductors, or market breadth. "
            "Prefer reliable reporting and exchange coverage."
        ),
        retry_query=(
            "Latest Nasdaq or S&P 500 or semiconductor sector news moving the U.S. market today. "
            "Prefer reliable reporting."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            "ft.com",
            "cnbc.com",
            "nasdaq.com",
        ),
    ),
    SearchTopic(
        name="ai_bigtech",
        query=(
            "Latest AI and big tech market-moving news on Nvidia, Microsoft, Apple, Amazon, "
            "Google, Meta, AMD, TSMC, ASML, or Broadcom. Prefer reliable reporting and company IR."
        ),
        retry_query=(
            "Latest AI infrastructure, data center, semiconductor, or big tech capex news today. "
            "Prefer reliable reporting and company IR."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            "ft.com",
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
            "Latest bitcoin market news on BTC ETF flows, regulation, institutional demand, or "
            "price-moving events. Prefer reliable reporting, ETF issuers, and regulators."
        ),
        retry_query=(
            "Latest spot bitcoin ETF flow or bitcoin regulation news today. Prefer reliable reporting "
            "and official sources."
        ),
        domain_filter=(
            "reuters.com",
            "bloomberg.com",
            "wsj.com",
            "ft.com",
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


def _is_allowed_domain(url: str, allowed_domains: tuple[str, ...]) -> bool:
    domain = normalize_domain(url)
    return any(domain_matches(domain, candidate) for candidate in allowed_domains)


def _build_client(api_key: str) -> Perplexity:
    return Perplexity(
        api_key=api_key,
        timeout=SEARCH_TIMEOUT_SECONDS,
        max_retries=1,
    )


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


def _search_once(
    *,
    client: Perplexity,
    query: str,
    domain_filter: tuple[str, ...],
    recency_filter: str,
) -> dict[str, Any]:
    try:
        response = client.search.create(
            query=query,
            max_results=SEARCH_MAX_RESULTS,
            search_domain_filter=list(domain_filter),
            search_recency_filter=recency_filter,
            country="US",
            search_mode="web",
        )
    except RateLimitError as exc:
        raise HttpFetchError(
            f"Perplexity Search API 호출 한도에 걸렸어요: {_format_status_error(exc)}"
        ) from exc
    except APITimeoutError as exc:
        raise HttpFetchError("Perplexity Search API 응답 시간이 너무 오래 걸렸어요.") from exc
    except APIConnectionError as exc:
        raise HttpFetchError("Perplexity Search API 연결을 열지 못했어요.") from exc
    except APIStatusError as exc:
        raise HttpFetchError(
            f"Perplexity Search API가 요청을 거절했어요: {_format_status_error(exc)}"
        ) from exc

    try:
        payload = response.model_dump()
    except AttributeError:
        if isinstance(response, dict):
            payload = response
        else:
            raise HttpFetchError("Perplexity Search API 응답 구조가 예상과 달라요.")

    if not isinstance(payload, dict):
        raise HttpFetchError("Perplexity Search API 응답 구조가 예상과 달라요.")

    return payload


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
        if not title or not url or not _is_allowed_domain(url, topic.domain_filter):
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


def fetch_news_from_perplexity(*, max_items: int, api_key: str) -> list[NewsItem]:
    del max_items

    if not api_key:
        logger.info("Perplexity API 키가 아직 없어 legacy 뉴스 수집으로 이어갈게요.")
        return []

    client = _build_client(api_key)
    collected: list[NewsItem] = []

    for topic in TOPIC_SPECS:
        try:
            payload = _search_once(
                client=client,
                query=topic.query,
                domain_filter=topic.domain_filter,
                recency_filter=topic.recency_filter,
            )
            topic_items = _parse_results(payload=payload, topic=topic)
            if len(topic_items) < TOPIC_RESULT_TARGET and topic.retry_query:
                retry_payload = _search_once(
                    client=client,
                    query=topic.retry_query,
                    domain_filter=topic.domain_filter,
                    recency_filter=topic.recency_filter,
                )
                topic_items.extend(_parse_results(payload=retry_payload, topic=topic))

            logger.info(
                "Perplexity에서 %s 토픽 후보를 %s건 확인했어요.",
                topic.name,
                len(topic_items),
            )
            collected.extend(topic_items)
        except HttpFetchError as exc:
            logger.warning("Perplexity에서 %s 토픽을 확인하는 중 문제가 있었어요: %s", topic.name, exc)

    return collected
