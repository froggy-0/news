from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any

from openai import OpenAI

from morning_brief.config import Settings
from morning_brief.data.news import merge_news_packets
from morning_brief.models import NewsItem
from morning_brief.prompting import build_prompt_cache_key, render_web_search_prompts

logger = logging.getLogger(__name__)

ALLOWED_NEWS_DOMAINS = [
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
]

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _needs_web_search_backfill(quality: dict) -> bool:
    if not isinstance(quality, dict):
        return False
    if str(quality.get("status", "ok")).lower() == "ok":
        return False

    return any(
        [
            int(quality.get("news_count", 0)) < 3,
            int(quality.get("preferred_news_count", 0)) < 2,
            int(quality.get("tier_1_news_count", 0)) < 1,
            int(quality.get("unique_news_domains", 0)) < 3,
            int(quality.get("fresh_news_count", 0)) < 2,
        ]
    )


def _build_search_context(packet: dict, quality: dict, max_results: int) -> dict[str, Any]:
    news = packet.get("news", [])
    existing_titles = [str(item.get("title", "")).strip() for item in news if isinstance(item, dict)]
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
            "official_etf_daily_flow_btc": packet.get("bitcoin", {}).get("official_etf_daily_flow_btc"),
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


def backfill_news_with_web_search(
    *,
    packet: dict,
    quality: dict,
    settings: Settings,
) -> tuple[list[dict], list[dict[str, str]]]:
    if not settings.openai_api_key or not settings.openai_web_search_enabled:
        return packet.get("news", []), []
    if not _needs_web_search_backfill(quality):
        return packet.get("news", []), []

    client = OpenAI(api_key=settings.openai_api_key)
    search_context = _build_search_context(
        packet=packet,
        quality=quality,
        max_results=settings.openai_web_search_max_results,
    )

    try:
        instructions, user_prompt = render_web_search_prompts(
            search_context_json=json.dumps(search_context, ensure_ascii=False, separators=(",", ":")),
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
            max_output_tokens=1200,
            prompt_cache_key=prompt_cache_key,
        )
        payload = _extract_json_object((response.output_text or "").strip())
        extra_items = _parse_web_news_items(payload)
        citations = _extract_web_citations(response)
        if not extra_items:
            return packet.get("news", []), citations

        merged_packet = merge_news_packets(
            existing_packet=packet.get("news", []),
            extra_items=extra_items,
            max_items=settings.max_news_items,
        )
        logger.info(
            "OpenAI 웹 검색으로 후보 뉴스 %s건을 더 확인했고, 최종 뉴스는 %s건으로 정리했어요.",
            len(extra_items),
            len(merged_packet),
        )
        return merged_packet, citations
    except Exception as exc:
        logger.warning("OpenAI 웹 검색으로 뉴스를 보강하는 중 문제가 있었어요: %s", exc)
        return packet.get("news", []), []
