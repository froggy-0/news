"""OpenAI web_search backfill for degraded research runs only."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from morning_brief.config import Settings
from morning_brief.data.news_packet import merge_news_packets
from morning_brief.data.news_selection import _merge_rank
from morning_brief.data.sources.domain_utils import normalize_domain
from morning_brief.llm_provider_policy import (
    CAPABILITY_WEB_BACKFILL,
    OPENAI_PROVIDER,
    capability_allowed,
)
from morning_brief.models import NewsItem
from morning_brief.observability import COLLECTED_ITEM_LOG_LIMIT, PipelineObserver
from morning_brief.prompting import build_prompt_cache_key, render_web_search_prompts

logger = logging.getLogger(__name__)

ALLOWED_NEWS_DOMAINS = [
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "marketwatch.com",
    "nasdaq.com",
    "coindesk.com",
    "federalreserve.gov",
    "home.treasury.gov",
    "sec.gov",
    "ishares.com",
    "bitbetf.com",
    "etfs.grayscale.com",
]

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
WEB_SEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "source": {"type": "string"},
                    "published_at": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["title", "url", "source", "published_at", "why_it_matters"],
            },
        }
    },
    "required": ["items"],
}
BACKFILL_SOURCE_EXCLUDE_PATTERNS = (
    "/authors/",
    "/opinion/",
    "/latest/",
    "partners.wsj.com",
    "downloads.coindesk.com",
    "data.coindesk.com",
    ".pdf",
    "cn.wsj.com",
    "jp.reuters.com",
    "/newsroom/whats-new",
    "/newsroom/press-releases",
    "/archives/edgar/data/",
)
BACKFILL_SOURCE_EXCLUDE_TITLES = (
    "home",
    "newsroom - sec.gov",
    "what's new - sec.gov",
    "press releases - sec.gov",
)
URL_ONLY_RE = re.compile(r"^https?://", re.IGNORECASE)
URL_WORD_RE = re.compile(r"[a-z]{3,}")
URL_DATE_PATTERNS = (
    re.compile(r"/(?P<year>20\d{2})/(?P<month>\d{2})/(?P<day>\d{2})/"),
    re.compile(r"(?P<month>\d{2})-(?P<day>\d{2})-(?P<year>20\d{2})"),
)
TRAILING_TRACKING_TOKEN_RE = re.compile(r"\b[a-z0-9]*\d[a-z0-9]{5,}\b$", re.IGNORECASE)


def _needs_web_search_backfill(quality: dict) -> bool:
    if not isinstance(quality, dict):
        return False
    if str(quality.get("status", "ok")).lower() == "ok":
        return False

    perplexity_item_count = int(quality.get("perplexity_item_count", 0))
    official_signal_count = int(quality.get("official_signal_count", 0))
    trusted_signal_count = int(quality.get("preferred_news_count", 0)) + official_signal_count
    authoritative_signal_count = int(quality.get("tier_1_news_count", 0)) + official_signal_count

    return any(
        [
            int(quality.get("news_count", 0)) < 3,
            trusted_signal_count < 2,
            authoritative_signal_count < 1,
            int(quality.get("unique_news_domains", 0)) < 3,
            int(quality.get("fresh_news_count", 0)) < 2,
            perplexity_item_count > 0 and int(quality.get("topic_coverage_count", 0)) < 2,
            perplexity_item_count > 0
            and int(quality.get("citation_backed_count", 0)) < perplexity_item_count,
        ]
    )


def _build_search_context(packet: dict, quality: dict, max_results: int) -> dict[str, Any]:
    news = packet.get("news", [])
    existing_titles = [
        str(item.get("title", "")).strip() for item in news if isinstance(item, dict)
    ]
    existing_urls = [str(item.get("url", "")).strip() for item in news if isinstance(item, dict)]
    top_tech = [
        {
            "label": point.get("label"),
            "change_pct": point.get("change_pct"),
        }
        for point in packet.get("tech_stocks", [])[:5]
        if isinstance(point, dict)
    ]
    return {
        "quality": quality,
        "max_results": max_results,
        "existing_titles": existing_titles,
        "existing_urls": existing_urls,
        "macro": packet.get("macro", []),
        "us_indices": packet.get("us_indices", []),
        "top_tech_stocks": top_tech,
        "bitcoin": {
            "spot": packet.get("bitcoin", {}).get("spot", {}),
            "official_etf_total_btc": packet.get("bitcoin", {}).get("official_etf_total_btc"),
        },
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {"items": []}

    match = JSON_BLOCK_RE.search(stripped)
    candidate = match.group(1) if match else stripped
    return json.loads(candidate)


def _extract_web_citations(response: object) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") == "web_search_call":
            action = getattr(item, "action", None)
            sources = getattr(action, "sources", None)
            if isinstance(sources, list):
                for source in sources:
                    url = str(getattr(source, "url", "") or "").strip()
                    title = str(getattr(source, "title", "") or "").strip()
                    if not url:
                        continue
                    key = (title, url)
                    if key in seen:
                        continue
                    seen.add(key)
                    citations.append({"title": title or url, "url": url})
            continue
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", "") != "output_text":
                continue
            for annotation in getattr(content, "annotations", []) or []:
                if getattr(annotation, "type", "") != "url_citation":
                    continue
                title = str(getattr(annotation, "title", "") or "").strip()
                url = str(getattr(annotation, "url", "") or "").strip()
                if not url:
                    continue
                key = (title, url)
                if key in seen:
                    continue
                seen.add(key)
                citations.append({"title": title or url, "url": url})

    return citations


def _parse_web_news_items(payload: dict) -> list[NewsItem]:
    if not isinstance(payload, dict):
        return []

    items: list[NewsItem] = []
    for raw_item in payload.get("items", []):
        if not isinstance(raw_item, dict):
            continue
        title = str(raw_item.get("title", "")).strip()
        url = str(raw_item.get("url", "")).strip()
        if not title or not url:
            continue

        source = str(raw_item.get("source", "")).strip() or url
        published_at = None
        published_raw = raw_item.get("published_at")
        if isinstance(published_raw, str) and published_raw.strip():
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        items.append(
            NewsItem(
                title=title,
                url=url,
                source=source,
                published_at=published_at.astimezone(timezone.utc) if published_at else None,
            )
        )

    return items


def _loggable_backfill_items(items: list[NewsItem]) -> list[dict[str, str]]:
    return [
        {
            "title": item.title,
            "url": item.url,
            "domain": normalize_domain(item.url).removeprefix("www."),
        }
        for item in items[:COLLECTED_ITEM_LOG_LIMIT]
    ]


def _fallback_items_from_citations(citations: list[dict[str, str]]) -> list[NewsItem]:
    items: list[NewsItem] = []
    seen_urls: set[str] = set()

    for citation in citations:
        title = str(citation.get("title", "")).strip()
        url = str(citation.get("url", "")).strip()
        normalized_url = url.lower()
        if not title or URL_ONLY_RE.match(title):
            title = _title_from_article_url(url)
        normalized_title = title.strip().lower()
        if (
            not title
            or not url
            or url in seen_urls
            or normalized_title in BACKFILL_SOURCE_EXCLUDE_TITLES
            or any(pattern in normalized_url for pattern in BACKFILL_SOURCE_EXCLUDE_PATTERNS)
        ):
            continue
        seen_urls.add(url)
        source_domain = normalize_domain(url).removeprefix("www.")
        published_at = _published_at_from_article_url(url)
        items.append(
            NewsItem(
                title=title,
                url=url,
                source=source_domain or "Unknown",
                published_at=published_at,
                provider="openai_web_search",
                citations=[url],
            )
        )

    return items


def _title_from_article_url(url: str) -> str:
    path = re.sub(r"/+$", "", re.sub(r"^https?://[^/]+", "", str(url or "").strip()))
    if not path:
        return ""
    segment = path.rsplit("/", 1)[-1]
    segment = segment.split("?", 1)[0].split("#", 1)[0]
    segment = re.sub(r"\.[a-z0-9]+$", "", segment, flags=re.IGNORECASE)
    if not segment or segment.isdigit():
        return ""
    words = [part for part in re.split(r"[-_]+", segment) if URL_WORD_RE.search(part or "")]
    if len(words) < 3:
        return ""
    title = " ".join(words).strip()
    title = TRAILING_TRACKING_TOKEN_RE.sub("", title).strip()
    if not title:
        return ""
    return title[:1].upper() + title[1:]


def _published_at_from_article_url(url: str) -> datetime | None:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return None
    path = urlparse(normalized_url).path
    for pattern in URL_DATE_PATTERNS:
        match = pattern.search(path)
        if not match:
            continue
        try:
            return datetime(
                year=int(match.group("year")),
                month=int(match.group("month")),
                day=int(match.group("day")),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    return None


def backfill_news_with_web_search(
    *,
    packet: dict,
    quality: dict,
    settings: Settings,
    observer: PipelineObserver | None = None,
) -> tuple[list[dict], list[dict[str, str]]]:
    if not settings.openai_web_search_enabled:
        logger.debug("OpenAI web_search 설정이 꺼져 있어 뉴스 백필은 건너뛸게요.")
        return packet.get("news", []), []
    if not capability_allowed(OPENAI_PROVIDER, CAPABILITY_WEB_BACKFILL):
        logger.warning(
            "OpenAI web_search 백필은 비활성화돼 있어서 현재 뉴스 묶음을 그대로 유지할게요."
        )
        return packet.get("news", []), []

    client = OpenAI(api_key=settings.openai_api_key)
    search_context = _build_search_context(
        packet=packet,
        quality=quality,
        max_results=settings.openai_web_search_max_results,
    )

    try:
        instructions, user_prompt = render_web_search_prompts(
            search_context_json=json.dumps(
                search_context, ensure_ascii=False, separators=(",", ":")
            ),
            settings=settings,
        )
        prompt_cache_key = build_prompt_cache_key(
            settings=settings,
            instructions=instructions + ":web-search",
            model_name=settings.openai_web_search_model,
        )
        response = client.responses.create(
            model=settings.openai_web_search_model,
            instructions=instructions,
            input=user_prompt,
            include=["web_search_call.action.sources"],
            tools=[
                {
                    "type": "web_search",
                    "filters": {"allowed_domains": ALLOWED_NEWS_DOMAINS},
                    "search_context_size": "low",
                    "user_location": {
                        "type": "approximate",
                        "country": "KR",
                        "timezone": settings.timezone,
                    },
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "web_search_backfill",
                    "schema": WEB_SEARCH_OUTPUT_SCHEMA,
                    "strict": True,
                }
            },
            max_output_tokens=1200,
            prompt_cache_key=prompt_cache_key,
        )
        output_text = (response.output_text or "").strip()
        payload = _extract_json_object(output_text)
        extra_items = _parse_web_news_items(payload)
        citations = _extract_web_citations(response)
        if not extra_items:
            citation_fallback_items = _fallback_items_from_citations(citations)
            if citation_fallback_items:
                merged_packet = merge_news_packets(
                    existing_packet=packet.get("news", []),
                    extra_items=citation_fallback_items,
                    max_items=settings.max_news_items,
                    merge_rank_fn=_merge_rank,
                )
                if observer is not None:
                    observer.log_event(
                        "web_backfill_result",
                        before_count=len(packet.get("news", [])),
                        extra_item_count=len(citation_fallback_items),
                        merged_count=len(merged_packet),
                        citation_count=len(citations),
                        citation_samples=citations[:COLLECTED_ITEM_LOG_LIMIT],
                        items=_loggable_backfill_items(citation_fallback_items),
                        output_preview=output_text[:200],
                        reason="source_only_fallback",
                    )
                logger.info(
                    "OpenAI 웹 검색 본문은 비어 있었지만 source 후보 %s건을 살려 최종 뉴스 %s건으로 정리했어요.",
                    len(citation_fallback_items),
                    len(merged_packet),
                )
                return merged_packet, citations
            if observer is not None:
                observer.log_event(
                    "web_backfill_result",
                    before_count=len(packet.get("news", [])),
                    extra_item_count=0,
                    merged_count=len(packet.get("news", [])),
                    citation_count=len(citations),
                    citation_samples=citations[:COLLECTED_ITEM_LOG_LIMIT],
                    output_preview=output_text[:200],
                    reason="no_items_parsed",
                )
            logger.info("OpenAI 웹 검색을 돌렸지만 새 기사 후보는 찾지 못했어요.")
            return packet.get("news", []), citations

        merged_packet = merge_news_packets(
            existing_packet=packet.get("news", []),
            extra_items=extra_items,
            max_items=settings.max_news_items,
            merge_rank_fn=_merge_rank,
        )
        if observer is not None:
            observer.log_event(
                "web_backfill_result",
                before_count=len(packet.get("news", [])),
                extra_item_count=len(extra_items),
                merged_count=len(merged_packet),
                citation_count=len(citations),
                items=_loggable_backfill_items(extra_items),
                reason="merged",
            )
        logger.info(
            "OpenAI 웹 검색으로 후보 뉴스 %s건을 더 확인했고, 최종 뉴스는 %s건으로 정리했어요.",
            len(extra_items),
            len(merged_packet),
        )
        return merged_packet, citations
    except Exception as exc:
        if observer is not None:
            observer.log_event("web_backfill_result", reason="error", detail=str(exc))
        logger.warning("OpenAI 웹 검색으로 뉴스를 보강하는 중 문제가 있었어요: %s", exc)
        return packet.get("news", []), []
