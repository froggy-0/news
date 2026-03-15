"""Perplexity Sonar Chat Completions 기반 토픽 요약 수집.

Search API(링크 나열)가 아닌 Sonar Chat Completions(LLM 종합 요약)를 사용하여
토픽별 시장 요약 텍스트 + 구조화 데이터 + citations를 수집한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from perplexity import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    Perplexity,
    RateLimitError,
)

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
SONAR_PROVIDER = "perplexity"

SONAR_TIMEOUT_SECONDS = 35
SONAR_TEMPERATURE = 0.1

SONAR_DENY_DOMAINS = [
    "-markets.ft.com",
    "-data.coindesk.com",
    "-downloads.coindesk.com",
    "-sponsored.bloomberg.com",
    "-cn.wsj.com",
    "-jp.reuters.com",
]

TOPIC_NAMES = ("macro", "us_equity", "ai_bigtech", "bitcoin")

TOPIC_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "market_topic_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "required": ["topic", "summary_text", "key_data_points", "market_implication"],
            "properties": {
                "topic": {"type": "string"},
                "summary_text": {
                    "type": "string",
                    "description": "2-4 paragraph narrative summary with specific numbers",
                },
                "key_data_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["label", "value", "change", "source"],
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "string"},
                            "change": {"type": "string"},
                            "source": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "market_implication": {
                    "type": "string",
                    "description": "One sentence: what this means for markets today",
                },
                "notable_stocks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["ticker", "reason", "change_pct"],
                        "properties": {
                            "ticker": {"type": "string"},
                            "reason": {"type": "string"},
                            "change_pct": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
}


@dataclass
class TopicSummary:
    """Sonar가 반환한 토픽별 시장 요약."""

    topic: str
    summary_text: str = ""
    key_data_points: list[dict[str, str]] = field(default_factory=list)
    market_implication: str = ""
    notable_stocks: list[dict[str, str]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    news_items: list[NewsItem] = field(default_factory=list)


def _build_sonar_client(api_key: str) -> Perplexity:
    return Perplexity(api_key=api_key, timeout=SONAR_TIMEOUT_SECONDS, max_retries=1)


def _is_weekend() -> bool:
    return datetime.now(timezone.utc).weekday() >= 5


def _time_range() -> str:
    return "last 7 days" if _is_weekend() else "last 24 hours"


def _recency_filter() -> str:
    return "week" if _is_weekend() else "day"


def _load_topic_prompt(topic: str) -> str:
    """Jinja 없이 간단히 토픽 프롬프트를 로드한다."""
    from pathlib import Path

    template_dir = Path(__file__).resolve().parent.parent / "prompts"
    template_path = template_dir / f"sonar_topic_{topic}.j2"
    if not template_path.exists():
        raise FileNotFoundError(f"Sonar 토픽 프롬프트를 찾을 수 없어요: {template_path}")
    raw = template_path.read_text(encoding="utf-8")
    return raw.replace("{{ time_range }}", _time_range())


def _load_system_prompt() -> str:
    from pathlib import Path

    template_dir = Path(__file__).resolve().parent.parent / "prompts"
    path = template_dir / "sonar_system.j2"
    return path.read_text(encoding="utf-8").strip()


def _retry_after_from_exc(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        return parse_retry_after_seconds(headers.get("Retry-After") or headers.get("retry-after"))
    return None


def _to_http_fetch_error(exc: Exception) -> HttpFetchError:
    if isinstance(exc, RateLimitError):
        msg = f"Perplexity Sonar 호출 한도에 걸렸어요: {exc}"
        open_circuit(SONAR_PROVIDER, msg)
        return HttpFetchError(
            msg,
            provider=SONAR_PROVIDER,
            retryable=False,
            rate_limited=True,
            retry_after_seconds=_retry_after_from_exc(exc),
        )
    if isinstance(exc, APITimeoutError):
        return HttpFetchError(
            "Perplexity Sonar 응답 시간이 너무 오래 걸렸어요.",
            provider=SONAR_PROVIDER,
            retryable=True,
        )
    if isinstance(exc, APIConnectionError):
        return HttpFetchError(
            "Perplexity Sonar 연결을 열지 못했어요.", provider=SONAR_PROVIDER, retryable=True
        )
    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            msg = f"Perplexity Sonar 호출 한도에 걸렸어요: {exc}"
            open_circuit(SONAR_PROVIDER, msg)
            return HttpFetchError(
                msg,
                provider=SONAR_PROVIDER,
                retryable=False,
                rate_limited=True,
                retry_after_seconds=_retry_after_from_exc(exc),
            )
        return HttpFetchError(
            f"Perplexity Sonar API가 요청을 거절했어요: status={status_code}",
            provider=SONAR_PROVIDER,
            retryable=status_code in policy_for(SONAR_PROVIDER).retryable_statuses,
        )
    return HttpFetchError(
        f"Perplexity Sonar를 호출하지 못했어요: {exc}", provider=SONAR_PROVIDER, retryable=False
    )


def _usage_int(obj: object, *keys: str) -> int | None:
    current = obj
    for k in keys:
        if current is None:
            return None
        current = getattr(current, k, None) if not isinstance(current, dict) else current.get(k)
    try:
        return int(current) if current is not None else None
    except (TypeError, ValueError):
        return None


def _usage_snapshot(response: object) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": _usage_int(usage, "prompt_tokens") or _usage_int(usage, "input_tokens"),
        "output_tokens": _usage_int(usage, "completion_tokens")
        or _usage_int(usage, "output_tokens"),
        "cached_input_tokens": None,
        "reasoning_tokens": None,
    }


def _parse_sonar_content(raw_content: str, topic: str) -> dict[str, Any]:
    """Sonar JSON 응답을 파싱한다."""
    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Sonar %s 응답 JSON 파싱 실패: %.200s", topic, text)
        return {
            "topic": topic,
            "summary_text": text,
            "key_data_points": [],
            "market_implication": "",
            "notable_stocks": [],
        }
    if not isinstance(data, dict):
        return {
            "topic": topic,
            "summary_text": str(data),
            "key_data_points": [],
            "market_implication": "",
            "notable_stocks": [],
        }
    data.setdefault("topic", topic)
    data.setdefault("summary_text", "")
    data.setdefault("key_data_points", [])
    data.setdefault("market_implication", "")
    data.setdefault("notable_stocks", [])
    return data


def _extract_citations(response: object) -> list[str]:
    citations = getattr(response, "citations", None)
    if isinstance(citations, list):
        return [str(c).strip() for c in citations if str(c).strip()]
    return []


def _citations_to_news_items(citations: list[str], topic: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for url in citations:
        if not url.startswith("http"):
            continue
        items.append(
            NewsItem(
                title=url.split("/")[-1].replace("-", " ").replace("_", " ")[:80] or url,
                url=url,
                source=_source_from_url(url),
                published_at=None,
                topic=topic,
                provider="perplexity_sonar",
                citations=[url],
            )
        )
    return items


def _source_from_url(url: str) -> str:
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return "Unknown"
    host = host.removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 2:
        return parts[-2].capitalize()
    return host or "Unknown"


def _sonar_chat_once(
    *,
    client: Perplexity,
    topic: str,
    model: str,
    max_tokens: int,
) -> tuple[dict[str, Any], list[str], dict[str, int | None]]:
    """Sonar Chat Completions API를 한 번 호출한다."""
    reason = disabled_reason(SONAR_PROVIDER)
    if reason:
        record_skip(SONAR_PROVIDER)
        raise HttpFetchError(f"Perplexity는 이번 실행에서 더 이상 쓰지 않을게요: {reason}")

    system_prompt = _load_system_prompt()
    user_prompt = _load_topic_prompt(topic)

    def perform() -> tuple[dict[str, Any], list[str], dict[str, int | None]]:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                search_domain_filter=SONAR_DENY_DOMAINS,
                search_recency_filter=_recency_filter(),
                response_format=TOPIC_SUMMARY_SCHEMA,
                temperature=SONAR_TEMPERATURE,
                max_tokens=max_tokens,
            )
        except (RateLimitError, APITimeoutError, APIConnectionError, APIStatusError) as exc:
            raise _to_http_fetch_error(exc) from exc

        content = ""
        if hasattr(response, "choices") and response.choices:
            msg = response.choices[0].message
            content = getattr(msg, "content", "") or ""

        parsed = _parse_sonar_content(content, topic)
        citations = _extract_citations(response)
        usage = _usage_snapshot(response)
        return parsed, citations, usage

    return execute_with_provider_retry(
        provider=SONAR_PROVIDER,
        operation=perform,
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=lambda exc, attempt, max_attempts, delay: logger.warning(
            "Perplexity Sonar를 다시 시도하는 중이에요 (%s/%s). topic=%s | %s | sleep=%.2fs",
            attempt,
            max_attempts,
            topic,
            exc,
            delay,
        ),
        retry_after_seconds_for_error=lambda exc: exc.retry_after_seconds
        if isinstance(exc, HttpFetchError)
        else None,
    )


def _record_sonar_usage(
    observer: PipelineObserver | None,
    topic: str,
    usage: dict[str, int | None],
) -> None:
    if observer is None:
        return
    failures = 1 if all(v is None for v in usage.values()) else 0
    observer.record_provider_usage(
        SONAR_PROVIDER,
        requests=1,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        usage_parse_failures=failures,
    )


def fetch_sonar_summaries(
    *,
    api_key: str,
    model: str = "sonar",
    max_tokens: int = 1500,
    topics: tuple[str, ...] = TOPIC_NAMES,
    observer: PipelineObserver | None = None,
) -> dict[str, TopicSummary]:
    """모든 토픽에 대해 Sonar 요약을 수집한다."""
    if not api_key.strip():
        logger.warning("Perplexity API 키가 없어서 Sonar 요약을 건너뛸게요.")
        return {}

    client = _build_sonar_client(api_key)
    results: dict[str, TopicSummary] = {}

    for topic in topics:
        try:
            parsed, citations, usage = _sonar_chat_once(
                client=client,
                topic=topic,
                model=model,
                max_tokens=max_tokens,
            )
            _record_sonar_usage(observer, topic, usage)

            summary = TopicSummary(
                topic=topic,
                summary_text=str(parsed.get("summary_text", "")),
                key_data_points=parsed.get("key_data_points", []),
                market_implication=str(parsed.get("market_implication", "")),
                notable_stocks=parsed.get("notable_stocks", []),
                citations=citations,
                news_items=_citations_to_news_items(citations, topic),
            )
            results[topic] = summary
            logger.info(
                "Sonar %s 요약 수집 완료: data_points=%d, citations=%d",
                topic,
                len(summary.key_data_points),
                len(citations),
            )
        except HttpFetchError as exc:
            logger.warning("Sonar %s 토픽 수집 실패: %s", topic, exc)
            if observer:
                observer.log_event("sonar_topic_failed", topic=topic, reason=str(exc))

    return results


def topic_summaries_to_dict(summaries: dict[str, TopicSummary]) -> dict[str, dict[str, Any]]:
    """TopicSummary를 JSON 직렬화 가능한 dict로 변환한다."""
    result: dict[str, dict[str, Any]] = {}
    for topic, s in summaries.items():
        result[topic] = {
            "topic": s.topic,
            "summary_text": s.summary_text,
            "key_data_points": s.key_data_points,
            "market_implication": s.market_implication,
            "notable_stocks": s.notable_stocks,
            "citations": s.citations,
        }
    return result


def collect_sonar_news_items(summaries: dict[str, TopicSummary]) -> list[NewsItem]:
    """모든 토픽 요약에서 NewsItem을 추출한다."""
    items: list[NewsItem] = []
    seen_urls: set[str] = set()
    for s in summaries.values():
        for item in s.news_items:
            if item.url not in seen_urls:
                seen_urls.add(item.url)
                items.append(item)
    return items
