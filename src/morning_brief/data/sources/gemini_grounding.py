"""Gemini Flash + Google Search grounding fallback.

Perplexity 유효 기사 0건 시 안전망으로 사용한다.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from google import genai
from google.genai.types import GenerateContentConfig, GoogleSearch, Tool

from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import (
    execute_with_provider_retry,
    open_circuit,
)
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)
GEMINI_PROVIDER = "gemini"


def _build_query(topic: str, keywords: list[str] | None = None) -> str:
    base = f"Latest {topic} market news today"
    if keywords:
        base += " " + " ".join(keywords[:3])
    return base


def _parse_grounding_items(response: object, topic: str) -> list[NewsItem]:
    """Grounding metadata에서 NewsItem을 추출한다."""
    items: list[NewsItem] = []
    candidate = getattr(response, "candidates", [None])[0] if response else None
    metadata = getattr(candidate, "grounding_metadata", None) if candidate else None
    chunks = getattr(metadata, "grounding_chunks", []) if metadata else []
    now = datetime.now(timezone.utc)
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if not web:
            continue
        url = getattr(web, "uri", "") or ""
        title = getattr(web, "title", "") or ""
        if url and title:
            items.append(
                NewsItem(
                    title=title.strip(),
                    url=url.strip(),
                    source="gemini_grounding",
                    published_at=now,
                    topic=topic,
                    provider="gemini",
                )
            )
    return items


def fetch_gemini_grounding(
    *,
    api_key: str,
    model: str,
    topics: list[str],
    keywords_by_topic: dict[str, list[str]] | None = None,
    max_items_per_topic: int = 4,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    """Gemini Flash + Google Search grounding으로 뉴스를 수집한다."""
    if not api_key.strip():
        return []

    client = genai.Client(api_key=api_key)
    all_items: list[NewsItem] = []
    started_at = time.perf_counter()

    for topic in topics:
        keywords = (keywords_by_topic or {}).get(topic)
        query = _build_query(topic, keywords)
        try:

            def _call(q=query, m=model):
                try:
                    return client.models.generate_content(
                        model=m,
                        contents=q,
                        config=GenerateContentConfig(
                            tools=[Tool(google_search=GoogleSearch())],
                            temperature=0.1,
                        ),
                    )
                except Exception as exc:
                    status = str(exc)
                    retryable = any(
                        s in status for s in ("500", "502", "503", "504", "UNAVAILABLE")
                    )
                    raise HttpFetchError(
                        f"Gemini 호출 실패: {exc}", provider=GEMINI_PROVIDER, retryable=retryable
                    ) from exc

            response = execute_with_provider_retry(
                provider=GEMINI_PROVIDER,
                operation=_call,
                should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
            )
            items = _parse_grounding_items(response, topic)[:max_items_per_topic]
            all_items.extend(items)
            if observer is not None:
                usage = getattr(response, "usage_metadata", None)
                observer.record_provider_usage(
                    GEMINI_PROVIDER,
                    requests=1,
                    input_tokens=getattr(usage, "prompt_token_count", None),
                    output_tokens=getattr(usage, "candidates_token_count", None),
                )
            log_structured(
                logger,
                event="selection.complete",
                message="Gemini grounding 수집을 마쳤어요.",
                provider=GEMINI_PROVIDER,
                topic=topic,
                kept_count=len(items),
            )
        except Exception as exc:
            log_structured(
                logger,
                event="error.raised",
                message="Gemini grounding이 실패했어요.",
                level=logging.WARNING,
                provider=GEMINI_PROVIDER,
                topic=topic,
                reason=str(exc),
                error_type=type(exc).__name__,
            )
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                open_circuit(GEMINI_PROVIDER, str(exc))
                break

    if observer is not None:
        observer.record_phase_duration(
            "gemini_grounding",
            int(round((time.perf_counter() - started_at) * 1000)),
        )
    return all_items
