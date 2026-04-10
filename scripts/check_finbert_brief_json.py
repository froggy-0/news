#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

DEFAULT_JSON_PATH = PROJECT_ROOT / "docs" / "briefs_2026-04-10.json"
NEWS_SECTIONS = ("featuredNews", "allNews", "news")
SIGNAL_SECTIONS = ("featuredXSignals", "allXSignals", "xSignals")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="brief JSON의 뉴스/X시그널 항목을 FinBERT로 다시 점수화해 persistence 상태를 확인합니다.",
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        default=str(DEFAULT_JSON_PATH),
        help=f"검사할 brief JSON 경로 (기본값: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="각 섹션에서 앞에서부터 N개 항목만 검사합니다. 0이면 전체를 검사합니다.",
    )
    return parser.parse_args()


def _load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _existing_score(item: dict[str, Any]) -> float | None:
    value = item.get("sentiment_score", item.get("sentimentScore"))
    return value if isinstance(value, (int, float)) else None


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _build_news_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": raw.get("title", ""),
        "rawTitle": raw.get("rawTitle", ""),
        "summaryKo": raw.get("summaryKo", ""),
        "summary_ko": raw.get("summary_ko", ""),
        "summary": raw.get("summary", ""),
        "interpretation": raw.get("interpretation", ""),
        "interpretation_ko": raw.get("interpretation_ko", ""),
        "why_it_matters": raw.get("why_it_matters", "") or raw.get("whyItMatters", ""),
        "rawSummary": raw.get("rawSummary", ""),
        "rawInterpretation": raw.get("rawInterpretation", ""),
        "url": raw.get("url", ""),
        "topic": raw.get("topic", "") or raw.get("category", ""),
        "existing_sentiment_score": _existing_score(raw),
    }


def _build_signal_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "headline": raw.get("headline", ""),
        "summary": raw.get("summary", ""),
        "why_it_matters": raw.get("why_it_matters", "") or raw.get("whyItMatters", ""),
        "content": raw.get("content", ""),
        "impact": raw.get("impact", ""),
        "rawContent": raw.get("rawContent", ""),
        "posted_at": raw.get("posted_at", "") or raw.get("postedAt", ""),
        "topic": raw.get("topic", ""),
        "existing_sentiment_score": _existing_score(raw),
    }


def _news_uses_fallback(item: dict[str, Any]) -> bool:
    return not (
        str(item.get("rawTitle", "")).strip()
        and str(item.get("rawSummary", "")).strip()
        and str(item.get("rawInterpretation", "")).strip()
    )


def _signal_uses_fallback(item: dict[str, Any]) -> bool:
    return not str(item.get("rawContent", "")).strip()


def _load_section_items(
    payload: dict[str, Any],
    section_name: str,
    *,
    limit: int,
    kind: str,
) -> list[dict[str, Any]]:
    raw_items = payload.get(section_name)
    if not isinstance(raw_items, list):
        return []

    builder = _build_news_item if kind == "news" else _build_signal_item
    items = [builder(raw) for raw in raw_items if isinstance(raw, dict)]
    if limit > 0:
        return items[:limit]
    return items


def _print_news_section(section_name: str, items: list[dict[str, Any]]) -> None:
    print(f"news_section: {section_name}")
    print(f"items_checked: {len(items)}")
    print(
        f"existing_scored_items: {sum(1 for item in items if item.get('existing_sentiment_score') is not None)}"
    )
    print(
        f"finbert_rescored_items: {sum(1 for item in items if item.get('sentiment_score') is not None)}"
    )
    print(f"fallback_items: {sum(1 for item in items if _news_uses_fallback(item))}")
    for index, item in enumerate(items, start=1):
        print(
            f"[{index:02d}] "
            f"existing={item.get('existing_sentiment_score')} "
            f"rescored={item.get('sentiment_score')} "
            f"confidence={item.get('sentiment_confidence')} "
            f"title={_first_non_empty(item.get('rawTitle'), item.get('title'))}"
        )
    print()


def _print_signal_section(section_name: str, items: list[dict[str, Any]]) -> None:
    print(f"signal_section: {section_name}")
    print(f"items_checked: {len(items)}")
    print(
        f"existing_scored_items: {sum(1 for item in items if item.get('existing_sentiment_score') is not None)}"
    )
    print(
        f"finbert_rescored_items: {sum(1 for item in items if item.get('sentiment_score') is not None)}"
    )
    print(f"fallback_items: {sum(1 for item in items if _signal_uses_fallback(item))}")
    for index, item in enumerate(items, start=1):
        print(
            f"[{index:02d}] "
            f"existing={item.get('existing_sentiment_score')} "
            f"rescored={item.get('sentiment_score')} "
            f"confidence={item.get('sentiment_confidence')} "
            f"content={_first_non_empty(item.get('rawContent'), item.get('content'), item.get('summary'), item.get('headline'))}"
        )
    print()


def main() -> int:
    args = _parse_args()
    target_path = Path(args.json_path).expanduser().resolve()
    if not target_path.exists():
        print(f"JSON 파일을 찾을 수 없습니다: {target_path}", file=sys.stderr)
        return 1

    payload = _load_payload(target_path)

    from morning_brief.config import load_settings
    from morning_brief.data.finbert_sentiment import (
        build_public_news_sentiment_text,
        enrich_news_packet,
        enrich_public_signal_items,
    )

    settings = load_settings()
    meta = payload.get("meta", {})

    print(f"json_path: {target_path}")
    print(f"sentiment_status_in_json: {meta.get('sentimentStatus')}")
    print(f"signal_sentiment_status_in_json: {meta.get('signalSentimentStatus', '(field absent)')}")
    print(f"news_sentiment_in_json: {meta.get('newsSentiment')}")
    print(f"signal_sentiment_in_json: {meta.get('signalSentiment')}")
    print()

    for section_name in NEWS_SECTIONS:
        items = _load_section_items(payload, section_name, limit=args.limit, kind="news")
        if not items:
            continue
        status = enrich_news_packet(
            items,
            settings,
            None,
            text_builder=build_public_news_sentiment_text,
        )
        print(f"news_section_status: {section_name} -> {status}")
        _print_news_section(section_name, items)

    for section_name in SIGNAL_SECTIONS:
        items = _load_section_items(payload, section_name, limit=args.limit, kind="signal")
        if not items:
            continue
        status = enrich_public_signal_items(items, settings, None)
        print(f"signal_section_status: {section_name} -> {status}")
        _print_signal_section(section_name, items)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
