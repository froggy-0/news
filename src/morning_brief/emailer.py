from __future__ import annotations

import base64
import hmac
import html
import json
import logging
import re
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from morning_brief.brief_formatting import (
    BTCData,
    MacroIndicator,
    SectionMap,
    StockItem,
    extract_sections,
    parse_event_calendar,
    parse_news_items,
    parse_sector_mapping,
)
from morning_brief.brief_formatting import (
    extract_brief_structure as _extract_brief_structure,
)
from morning_brief.brief_formatting import (
    split_footer_note_block as _split_footer_note_block,
)
from morning_brief.brief_formatting import (
    split_reference_block as _split_reference_block,
)
from morning_brief.brief_formatting import (
    split_section_groups as _split_section_groups,
)
from morning_brief.config import Settings
from morning_brief.data.market_policy import is_rate_canonical_key
from morning_brief.logging_utils import log_structured
from morning_brief.subscriptions.models import ActiveRecipient
from morning_brief.subscriptions.repository import SubscriptionRepository
from morning_brief.subscriptions.supabase_repository import SupabaseSubscriptionRepository

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

logger = logging.getLogger(__name__)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PERCENT_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%")
UP_TOKENS = ("올랐", "상승", "강세", "반등", "높아졌", "증가", "확대", "유입", "개선", "회복")
DOWN_TOKENS = ("내렸", "하락", "약세", "밀렸", "낮아졌", "감소", "축소", "유출", "둔화", "후퇴")
FLAT_TOKENS = ("보합", "유지", "비슷", "변동이 크지", "큰 변화는 없")
EMAIL_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
PROJECT_GITHUB_URL = "https://github.com/froggy-0/news"
DEFAULT_UNSUBSCRIBE_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
UNSUBSCRIBE_TOKEN_VERSION = 1
NONE_LIKE_TEXTS = {"", "none", "null", "n/a", "na"}
_HERO_KOSPI_HINTS = ("코스피", "코스닥", "한국장", "국내 증시")
_SOURCE_AGG_HINTS = ("집계", "큐레이션", "요약 출처", "aggregated", "summary")
_SNAPSHOT_LABELS = {
    "us10y": "미국 10년물",
    "dxy": "DXY",
    "vix": "VIX",
    "usdkrw": "원/달러",
    "nq_futures": "나스닥 선물",
    "btc": "BTC 현물",
}

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

    from morning_brief.unified_output import UnifiedOutput
else:  # pragma: no cover - runtime import guard
    Credentials = Any


@dataclass(frozen=True)
class _EmailSection:
    heading: str
    content: str
    groups: dict[str, tuple[str, str]]


@dataclass(frozen=True)
class _EmailNewsItem:
    headline: str
    market_meaning: str
    korea_takeaway: str
    url: str
    safe_url: str | None
    source_name: str | None


@dataclass(frozen=True)
class _EmailBriefRow:
    name: str
    change_text: str
    context_text: str
    context_html: Markup
    tone: str


@dataclass(frozen=True)
class _EmailSourceItem:
    headline: str
    source_name: str
    source_kind: str
    safe_url: str | None


def _gmail_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials as GoogleCredentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Gmail 전송 의존성이 설치되지 않았어요. "
            "requirements.txt를 설치한 뒤 다시 실행해 주세요."
        ) from exc
    return Request, GoogleCredentials, InstalledAppFlow, build


def _first_non_empty_paragraph(text: str) -> str:
    for paragraph in (part.strip() for part in text.split("\n\n")):
        if paragraph:
            return paragraph
    return ""


def _first_metric_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped[2:].strip() if stripped.startswith("- ") else stripped
    return ""


def _format_display_date(title: str, subject: str) -> str:
    match = DATE_RE.search(title) or DATE_RE.search(subject)
    if not match:
        return ""
    year, month, day = match.group(1).split("-")
    weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    try:
        from datetime import datetime

        weekday = weekdays[datetime(int(year), int(month), int(day)).weekday()]
    except ValueError:
        weekday = ""
    return f"{year}년 {int(month)}월 {int(day)}일 {weekday} · 오전 8시 브리핑".strip()


def _build_email_sections(sections: list[tuple[str, str]]) -> list[_EmailSection]:
    return [
        _EmailSection(
            heading=heading,
            content=content,
            groups=_split_section_groups(content),
        )
        for heading, content in sections
    ]


def _build_top_summary_lines(sections: list[_EmailSection]) -> list[str]:
    lines: list[str] = []
    for section in sections:
        conclusion = section.groups["conclusion"][1]
        insight = section.groups["insight"][1]
        candidate = _first_non_empty_paragraph(conclusion) or _first_non_empty_paragraph(insight)
        if candidate:
            if candidate.startswith("- "):
                candidate = candidate[2:].strip()
            lines.append(candidate)
        if len(lines) >= 3:
            break
    return lines


def _load_email_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(EMAIL_TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _first_metric_lines(text: str, *, limit: int) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        lines.append(stripped[2:].strip() if stripped.startswith("- ") else stripped)
        if len(lines) >= limit:
            break
    return lines


def _first_sentence(text: str) -> str:
    paragraph = _first_non_empty_paragraph(text)
    if not paragraph:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", paragraph)
    return parts[0].strip() if parts else paragraph.strip()


def _safe_link(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc):
        return url.strip()
    return None


def _source_name(url: str | None) -> str | None:
    if not url:
        return None

    safe_url = _safe_link(url)
    if safe_url is None:
        return None

    parsed = urlparse(safe_url)
    hostname = _normalized_hostname(parsed.netloc)
    if not hostname:
        return None

    mapped_name = _mapped_source_name(hostname, parsed.path)
    if mapped_name == "":
        return None
    if mapped_name is not None:
        return mapped_name
    return _fallback_source_name(hostname)


def _normalized_hostname(netloc: str) -> str:
    hostname = netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if hostname.endswith("twitter.com"):
        return "x.com"
    return hostname


def _mapped_source_name(hostname: str, path: str) -> str | None:
    if hostname == "x.com":
        path_parts = [part for part in path.split("/") if part]
        return f"X (@{path_parts[0]})" if path_parts else "X"
    if hostname == "news.google.com":
        return "Google News"
    if hostname == "markets.ft.com":
        return "" if "/data/" in path else "Financial Times"

    hostname_mappings = (
        ("ft.com", "Financial Times"),
        ("reuters.com", "Reuters"),
        ("wsj.com", "The Wall Street Journal"),
        ("bloomberg.com", "Bloomberg"),
        ("cnbc.com", "CNBC"),
        ("bitcoin.com", "Bitcoin.com News"),
        ("finance.yahoo.com", "Yahoo Finance"),
        ("yahoo.com", "Yahoo Finance"),
    )
    for suffix, label in hostname_mappings:
        if hostname.endswith(suffix):
            return label
    return None


def _fallback_source_name(hostname: str) -> str | None:
    root = hostname.split(".")
    if len(root) >= 2:
        return root[-2].replace("-", " ").title()
    return hostname or None


def _source_kind(raw_source_name: str | None, safe_url: str | None) -> str:
    if safe_url:
        hostname = _normalized_hostname(urlparse(safe_url).netloc)
        if hostname == "x.com":
            return "공식 X"
        if hostname == "news.google.com":
            return "뉴스 큐레이션"
    raw = _sanitize_optional_text(raw_source_name or "").lower()
    if any(token in raw for token in _SOURCE_AGG_HINTS):
        return "집계 참고"
    return "원문 기사"


def _display_source_name(raw_source_name: str | None, safe_url: str | None) -> str | None:
    derived = _source_name(safe_url)
    if derived:
        return derived

    raw = _sanitize_optional_text(raw_source_name or "")
    if not raw:
        return None
    raw = re.sub(r"\([^)]*(?:집계|요약)[^)]*\)", "", raw).strip(" -–—")
    raw = raw.replace("NASDAQ.com", "Nasdaq")
    return raw or None


def _news_source_label(raw_source_name: str | None, safe_url: str | None) -> str | None:
    source_name = _display_source_name(raw_source_name, safe_url)
    if not source_name:
        return None
    return f"{_source_kind(raw_source_name, safe_url)} · {source_name}"


def _sanitize_optional_text(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    if normalized.lower() in NONE_LIKE_TEXTS:
        return ""
    return normalized


def _build_hero_context(raw: str) -> dict[str, object]:
    summary, alerts = _split_hero(raw)
    reason = ""
    kospi_impact = ""
    secondary_alerts: list[str] = []

    for alert in alerts:
        normalized = _sanitize_optional_text(alert)
        if not normalized:
            continue
        if not kospi_impact and any(hint in normalized for hint in _HERO_KOSPI_HINTS):
            kospi_impact = normalized
            continue
        if not reason:
            reason = normalized
            continue
        secondary_alerts.append(normalized)

    verdict = _sanitize_optional_text(summary) or "오늘 확인이 필요한 변수가 많습니다."
    if not reason and secondary_alerts:
        reason, secondary_alerts = secondary_alerts[0], secondary_alerts[1:]

    if "매수 관심" in verdict:
        tone = "up"
    elif "리스크 주의" in verdict:
        tone = "down"
    else:
        tone = "flat"

    return {
        "hero_summary": verdict,
        "hero_alerts": secondary_alerts,
        "hero_verdict": verdict,
        "hero_reason": reason,
        "hero_kospi_impact": kospi_impact,
        "hero_tone": tone,
    }


def _display_percent_token(token: str) -> str:
    direction = _percent_direction(token)
    abs_change = _abs_percent_text(token)
    if direction == "up":
        return f"▲{abs_change}"
    if direction == "down":
        return f"▼{abs_change}"
    if direction == "flat":
        return "—"
    return token


def _parse_news_metric_line(line: str) -> tuple[str, str, str, str | None]:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 2:
        parts = [part.strip() for part in re.split(r"\s*[—–]\s*", line)]
    source_url = None
    content_parts = parts
    if len(parts) >= 2 and _safe_link(parts[-1] or ""):
        source_url = parts[-1].strip() or None
        content_parts = parts[:-1]

    if len(content_parts) >= 3:
        return (
            content_parts[0].strip() or line.strip(),
            _sanitize_optional_text(content_parts[1].strip()),
            _sanitize_optional_text(" | ".join(content_parts[2:])),
            source_url,
        )
    if len(content_parts) == 2:
        return (
            content_parts[0].strip() or line.strip(),
            _sanitize_optional_text(content_parts[1].strip()),
            "",
            source_url,
        )
    return line.strip(), "", "", source_url


def _extract_layer_one_text(sections: list[_EmailSection], notice: str, title: str) -> str:
    summary_lines = _build_top_summary_lines(sections)
    if summary_lines:
        return summary_lines[0]
    if sections:
        first_section = sections[0]
        return _first_sentence(first_section.groups["conclusion"][1]) or _first_sentence(
            first_section.groups["insight"][1]
        )
    return notice or title


def _find_layer_section(
    sections: list[_EmailSection],
    *,
    exact_heading: str | None = None,
    contains_heading: str | None = None,
) -> _EmailSection | None:
    for section in sections:
        if exact_heading is not None and section.heading == exact_heading:
            return section
        if contains_heading is not None and contains_heading in section.heading:
            return section
    return None


def _fallback_section_text(section: _EmailSection | None) -> str:
    if section is None:
        return ""
    return section.content.strip()


def _split_layer_three_metric_lines(section: _EmailSection | None) -> tuple[list[str], list[str]]:
    if section is None:
        return [], []

    stock_lines: list[str] = []
    macro_lines: list[str] = []
    in_macro_block = False
    for raw_line in section.groups["metrics"][1].splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "거시 지표":
            in_macro_block = True
            continue
        if not stripped.startswith("- "):
            continue
        line = stripped[2:].strip()
        if in_macro_block:
            macro_lines.append(line)
        else:
            stock_lines.append(line)

    # macro 그룹이 별도로 분리된 경우 (brief_formatting에서 거시 지표 소제목 인식)
    if not macro_lines and "macro" in section.groups:
        for raw_line in section.groups["macro"][1].splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("- "):
                macro_lines.append(stripped[2:].strip())

    return stock_lines, macro_lines


def _build_news_items(
    sections: list[_EmailSection],
    references: list[str],
    *,
    limit: int = 3,
) -> list[_EmailNewsItem]:
    safe_reference_urls = [
        safe_url
        for reference in references
        for safe_url in [_safe_link(reference.split(" — ", 1)[-1].strip())]
        if safe_url
    ]
    items: list[_EmailNewsItem] = []

    important_news = next(
        (
            section
            for section in sections
            if section.heading == "중요한 뉴스"
            or "LAYER 2" in section.heading
            or "주요 뉴스" in section.heading
        ),
        None,
    )
    if important_news is not None:
        section_clues = [
            _first_sentence(important_news.groups["conclusion"][1]),
            _first_sentence(important_news.groups["insight"][1]),
        ]
        fallback_market_meaning = next((item for item in section_clues if item), "")
        fallback_korea_takeaway = _first_sentence(important_news.groups["watch"][1])
        for index, line in enumerate(
            _first_metric_lines(important_news.groups["metrics"][1], limit=limit)
        ):
            headline, market_meaning, korea_takeaway, source_url = _parse_news_metric_line(line)
            safe_url = _safe_link(source_url or "")
            if safe_url is None and index < len(safe_reference_urls):
                safe_url = safe_reference_urls[index]
            items.append(
                _EmailNewsItem(
                    headline=headline,
                    market_meaning=_sanitize_optional_text(
                        market_meaning or fallback_market_meaning
                    ),
                    korea_takeaway=_sanitize_optional_text(
                        korea_takeaway or fallback_korea_takeaway
                    ),
                    url=safe_url or "",
                    safe_url=safe_url,
                    source_name=_source_name(safe_url),
                )
            )

    if items:
        return items[:limit]

    for index, section in enumerate(sections[:limit]):
        safe_url = safe_reference_urls[index] if index < len(safe_reference_urls) else None
        market_meaning = _first_sentence(section.groups["conclusion"][1]) or _first_sentence(
            section.groups["insight"][1]
        )
        korea_takeaway = _first_sentence(section.groups["watch"][1])
        items.append(
            _EmailNewsItem(
                headline=section.heading,
                market_meaning=_sanitize_optional_text(
                    market_meaning or _first_non_empty_paragraph(section.content)
                ),
                korea_takeaway=_sanitize_optional_text(korea_takeaway),
                url=safe_url or "",
                safe_url=safe_url,
                source_name=_source_name(safe_url),
            )
        )
    return items


def _stock_name_from_line(line: str, fallback: str) -> str:
    percent_match = PERCENT_RE.search(line)
    if percent_match is None:
        return fallback
    prefix = line[: percent_match.start()].strip(" -:|")
    if not prefix:
        return fallback
    cleaned = re.split(r"(?:\([^)]*\))?\s*(은|는|이|가)\s", prefix)[0].strip()
    return cleaned or fallback


def _row_tone(line: str, change_text: str) -> str:
    direction = _percent_direction(change_text) or _token_direction(line) or "flat"
    if direction == "up":
        return "up"
    if direction == "down":
        return "down"
    return "flat"


def _strip_inline_source(text: str) -> str:
    return re.sub(r"\s*\|\s*\[출처:[^\]]+\]\s*$", "", text).strip()


def _abs_percent_text(change_text: str) -> str:
    return change_text.strip().lstrip("+-")


def _stock_summary_text(*, name: str, change_text: str, context_text: str) -> str:
    direction = _percent_direction(change_text) or _token_direction(context_text) or "flat"
    abs_change = _abs_percent_text(change_text)
    if direction == "up":
        verb = "상승"
    elif direction == "down":
        verb = "하락"
    else:
        verb = "보합"

    normalized_name = name.strip()
    if normalized_name in {"BTC", "BTC-USD", "비트코인", "비트코인 현물"}:
        price_match = re.search(r"([\d,]+(?:\.\d+)?)달러", context_text)
        if price_match is not None:
            return f"비트코인은 전일 대비 {abs_change} {verb}, 현재 ${price_match.group(1)}입니다."
        return f"비트코인은 전일 대비 {abs_change} {verb}했습니다."

    return f"{normalized_name}는 전일 대비 {abs_change} {verb}했습니다."


def _build_stock_row(line: str, fallback_heading: str) -> _EmailBriefRow | None:
    parts = [part.strip() for part in line.split("|")]
    normalized_line = _strip_inline_source(line)
    percent_match = PERCENT_RE.search(normalized_line)
    if percent_match is None:
        return None

    if len(parts) >= 3:
        name = parts[0] or fallback_heading
        change_text = parts[1] or percent_match.group(0)
        context_text = " | ".join(part for part in parts[2:] if part)
        context_text = _strip_inline_source(context_text)
    else:
        change_text = percent_match.group(0)
        name = _stock_name_from_line(normalized_line, fallback=fallback_heading)
        context_text = normalized_line

    summary_text = _stock_summary_text(
        name=name,
        change_text=change_text,
        context_text=context_text or normalized_line,
    )

    return _EmailBriefRow(
        name=name,
        change_text=change_text,
        context_text=summary_text,
        context_html=Markup(_render_body_line(summary_text)),
        tone=_row_tone(normalized_line, change_text),
    )


def _build_stock_rows(sections: list[_EmailSection], *, limit: int = 6) -> list[_EmailBriefRow]:
    layer_three_section = _find_layer_section(sections, contains_heading="LAYER 3")
    rows: list[_EmailBriefRow] = []
    seen_contexts: set[str] = set()
    if layer_three_section is not None:
        candidate_lines, _ = _split_layer_three_metric_lines(layer_three_section)
        _append_stock_rows(
            rows=rows,
            seen_contexts=seen_contexts,
            candidate_lines=candidate_lines[:limit],
            fallback_heading=layer_three_section.heading,
            limit=limit,
        )
        return rows

    for section in sections:
        candidate_lines = [
            *_first_metric_lines(section.groups["metrics"][1], limit=limit),
            *_first_metric_lines(section.groups["watch"][1], limit=limit),
        ]
        _append_stock_rows(
            rows=rows,
            seen_contexts=seen_contexts,
            candidate_lines=candidate_lines,
            fallback_heading=section.heading,
            limit=limit,
        )
        if len(rows) >= limit:
            return rows
    return rows


def _append_stock_rows(
    *,
    rows: list[_EmailBriefRow],
    seen_contexts: set[str],
    candidate_lines: list[str],
    fallback_heading: str,
    limit: int,
) -> None:
    for line in candidate_lines:
        row = _build_stock_row(line, fallback_heading)
        if row is None or row.context_text in seen_contexts:
            continue
        seen_contexts.add(row.context_text)
        rows.append(row)
        if len(rows) >= limit:
            return


def _split_macro_line(line: str) -> tuple[str, str]:
    normalized_line = _strip_inline_source(line)
    for particle in ("는 ", "은 ", "가 ", "이 "):
        idx = normalized_line.find(particle)
        if idx >= 0 and idx > 0:
            label = normalized_line[:idx].strip()
            value = normalized_line[idx + len(particle) :].strip()
            return label or "거시 지표", value or normalized_line
    return "거시 지표", normalized_line


def _build_macro_rows(sections: list[_EmailSection]) -> list[tuple[str, Markup]]:
    layer_three_section = _find_layer_section(sections, contains_heading="LAYER 3")
    candidate_lines: list[str] = []
    if layer_three_section is not None:
        _, layer_three_macro_lines = _split_layer_three_metric_lines(layer_three_section)
        candidate_lines.extend(layer_three_macro_lines[:4])
    else:
        macro_keywords = ("미국 10년물", "달러 인덱스", "VIX", "공포탐욕", "US10Y", "DXY")
        macro_section = next(
            (section for section in sections if section.heading == "거시 환경"), None
        )
        if macro_section is not None:
            candidate_lines.extend(_first_metric_lines(macro_section.groups["metrics"][1], limit=4))
        else:
            layer_one_section = _find_layer_section(sections, contains_heading="LAYER 1")
            fallback_sections = [layer_one_section] if layer_one_section is not None else sections
            for section in fallback_sections:
                for line in _first_metric_lines(section.groups["metrics"][1], limit=8):
                    if any(keyword in line for keyword in macro_keywords):
                        candidate_lines.append(line)
                if len(candidate_lines) >= 4:
                    break
    rows: list[tuple[str, Markup]] = []
    seen_rows: set[tuple[str, str]] = set()
    for line in candidate_lines[:4]:
        label, value = _split_macro_line(line)
        key = (label, value)
        if key in seen_rows:
            continue
        seen_rows.add(key)
        rows.append((label, Markup(_render_body_line(value))))
    return rows


def _build_reference_items(references: list[str]) -> list[dict[str, str | None]]:
    items: list[dict[str, str | None]] = []
    for reference in references:
        if " — " in reference:
            label, url = reference.split(" — ", 1)
        else:
            label, url = reference, reference
        safe_url = _safe_link(url.strip())
        items.append(
            {
                "label": label.strip() or url.strip(),
                "url": url.strip(),
                "safe_url": safe_url,
            }
        )
    return items


def _build_news_source_items(
    news_items: list[_EmailNewsItem],
    reference_items: list[dict[str, str | None]],
) -> list[_EmailSourceItem]:
    items: list[_EmailSourceItem] = []
    seen_sources: set[tuple[str, str]] = set()

    for item in news_items:
        source_name = _display_source_name(item.source_name, item.safe_url)
        if not source_name:
            continue
        source_kind = _source_kind(item.source_name, item.safe_url)
        key = (source_kind, source_name)
        if key in seen_sources:
            continue
        seen_sources.add(key)
        items.append(
            _EmailSourceItem(
                headline=item.headline,
                source_name=source_name,
                source_kind=source_kind,
                safe_url=item.safe_url,
            )
        )

    for reference_item in reference_items:
        safe_url = reference_item.get("safe_url")
        if not isinstance(safe_url, str) or not safe_url:
            continue
        source_name = _display_source_name(str(reference_item.get("label") or ""), safe_url)
        if not source_name:
            continue
        source_kind = _source_kind(str(reference_item.get("label") or ""), safe_url)
        key = (source_kind, source_name)
        if key in seen_sources:
            continue
        seen_sources.add(key)
        items.append(
            _EmailSourceItem(
                headline=str(reference_item.get("label") or source_name),
                source_name=source_name,
                source_kind=source_kind,
                safe_url=safe_url,
            )
        )

    return items


def _market_source_lines() -> list[str]:
    return [
        "거시 지표: FRED, yfinance",
        "미국 지수/기술주: Stooq",
        "비트코인: CoinGecko",
        "X 시그널: Grok",
    ]


def _urlsafe_token(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _build_unsubscribe_token(*, settings: Settings, recipient: ActiveRecipient) -> str:
    issued_at = int(time.time())
    payload = {
        "v": UNSUBSCRIBE_TOKEN_VERSION,
        "sub": recipient.subscriber_id,
        "email": recipient.email,
        "newsletter": recipient.newsletter,
        "action": "unsubscribe",
        "iat": issued_at,
        "exp": issued_at + DEFAULT_UNSUBSCRIBE_TOKEN_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        settings.subscription_token_secret.encode("utf-8"),
        payload_bytes,
        sha256,
    ).digest()
    return f"{_urlsafe_token(payload_bytes)}.{_urlsafe_token(signature)}"


def _unsubscribe_url(
    *,
    settings: Settings,
    recipient: ActiveRecipient,
) -> str:
    path = settings.subscription_unsubscribe_path.strip() or "/unsubscribe"
    if not path.startswith("/"):
        path = f"/{path}"
    token = _build_unsubscribe_token(settings=settings, recipient=recipient)
    return f"{settings.public_app_base_url}{path}?{urlencode({'token': token})}"


def _primary_cta(reference_items: list[dict[str, str | None]]) -> dict[str, str]:
    first_reference = next(
        (
            item
            for item in reference_items
            if isinstance(item.get("safe_url"), str)
            and item["safe_url"]
            and _source_name(str(item["safe_url"])) is not None
        ),
        None,
    )
    if first_reference is not None:
        return {"label": "대표 출처 열기", "url": str(first_reference["safe_url"])}
    return {"label": "GitHub에서 보기", "url": PROJECT_GITHUB_URL}


# ---------------------------------------------------------------------------
# V2 이메일 빌더 함수들
# ---------------------------------------------------------------------------

_DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def _build_snapshot_badges(packet: dict) -> list[dict]:
    # DEPRECATED: unified-pipeline — _build_snapshot_badges_v2(unified) 로 교체 예정
    """상단 핵심 수치 6개를 이메일용 배지로 정리."""
    macro_points = packet.get("macro", []) if isinstance(packet.get("macro", []), list) else []
    korea_points = (
        packet.get("korea_watch", []) if isinstance(packet.get("korea_watch", []), list) else []
    )
    btc_spot = packet.get("bitcoin", {}).get("spot", {}) or {}

    ordered_points: list[dict[str, Any]] = [
        _find_point_by_key(macro_points, "us10y"),
        _find_point_by_key(macro_points, "dxy"),
        _find_point_by_key(macro_points, "vix"),
        _find_point_by_key(korea_points, "usdkrw"),
        _find_point_by_key(korea_points, "nq_futures"),
        {
            **btc_spot,
            "canonical_key": "btc",
            "label": "BTC 현물",
            "resolution_reason": btc_spot.get("resolution_reason", ""),
        },
    ]

    badges: list[dict[str, str]] = []
    for point in ordered_points:
        canonical_key = str(point.get("canonical_key", "")).strip().lower()
        label = _SNAPSHOT_LABELS.get(canonical_key, str(point.get("label", "")) or "시장 지표")
        badges.append(
            {
                "label": label,
                "value": _snapshot_value_text(point),
                "change": _snapshot_change_text(point),
                "direction": _snapshot_direction(point),
                "status_text": _snapshot_status_text(point),
            }
        )

    return badges


def _build_snapshot_badges_v2(unified: "UnifiedOutput") -> list[dict]:
    """QuantitativeLayer 기반 배지 생성 (v2).

    unified-pipeline: unified.quantitative의 TickerPoint 목록을 직접 소비.
    FC-1 change_pct 소수 2자리 적용 (TickerPoint.change 이미 포맷됨).
    """
    q = unified.quantitative
    ticker_order = [q.us10y, q.dxy, q.vix, q.usdkrw, q.nq_futures, q.btc_spot]
    badges: list[dict] = []
    for ticker in ticker_order:
        if ticker is None:
            badges.append(
                {
                    "label": "",
                    "value": "",
                    "change": "",
                    "direction": "flat",
                    "status_text": "이번 집계에서는 확인되지 않았어요.",
                }
            )
            continue
        label = _SNAPSHOT_LABELS.get(ticker.symbol.lower(), ticker.label)
        # BTC는 canonical_key가 "btc"이므로 label lookup 시도
        if ticker.symbol == "BTC":
            label = _SNAPSHOT_LABELS.get("btc", ticker.label)
        badges.append(
            {
                "label": label,
                "value": ticker.value_fmt or "",
                "change": ticker.change or "",
                "direction": ticker.trend or "flat",
                "status_text": "전일 값" if ticker.is_cached else "",
            }
        )
    return badges


def _format_volume(volume: float) -> str:
    """거래량을 읽기 쉬운 형식으로 포맷."""
    if volume >= 1_000_000_000:
        return f"${volume / 1_000_000_000:.1f}B"
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"${volume / 1_000:.0f}K"
    return f"${volume:.0f}"


def _format_pct_badge(value: float | None) -> tuple[str, str]:
    pct = value or 0.0
    return (
        f"{pct:+.1f}%",
        "up" if pct > 0 else "down" if pct < 0 else "flat",
    )


def _find_point_by_key(points: list[dict[str, Any]], canonical_key: str) -> dict[str, Any]:
    normalized = canonical_key.strip().lower()
    return next(
        (
            point
            for point in points
            if str(point.get("canonical_key", "")).strip().lower() == normalized
        ),
        {},
    )


def _snapshot_value_text(point: dict[str, Any]) -> str:
    price = point.get("price")
    if price is None:
        return "확인 중"

    canonical_key = str(point.get("canonical_key", "")).strip().lower()
    numeric_price = float(price)
    if canonical_key == "btc":
        return f"${numeric_price:,.0f}"
    if canonical_key == "vix":
        return f"{numeric_price:.1f}"
    if canonical_key == "usdkrw":
        return f"{numeric_price:,.2f}"
    if canonical_key == "nq_futures":
        return f"{numeric_price:,.0f}"
    if is_rate_canonical_key(canonical_key):
        return f"{numeric_price:.2f}%"
    return f"{numeric_price:,.2f}"


def _snapshot_change_text(point: dict[str, Any]) -> str:
    canonical_key = str(point.get("canonical_key", "")).strip().lower()
    if point.get("price") is None:
        return ""
    if is_rate_canonical_key(canonical_key):
        change_bps = point.get("change_bps")
        if change_bps is None:
            return ""
        return f"{float(change_bps):+.0f}bp"

    change_pct = point.get("change_pct")
    if change_pct is None:
        return ""
    return f"{float(change_pct):+.2f}%"


def _snapshot_direction(point: dict[str, Any]) -> str:
    canonical_key = str(point.get("canonical_key", "")).strip().lower()
    if is_rate_canonical_key(canonical_key):
        change = point.get("change_bps")
    else:
        change = point.get("change_pct")
    if change is None:
        return "flat"
    numeric = float(change)
    if numeric > 0:
        return "up"
    if numeric < 0:
        return "down"
    return "flat"


def _snapshot_status_text(point: dict[str, Any]) -> str:
    if point.get("price") is None:
        return str(point.get("resolution_reason") or "이번 집계에서는 확인되지 않았어요.")
    if point.get("is_previous_value"):
        return "전일 값"
    return ""


def _header_signal(hero_verdict: str, hero_tone: str, data_quality_status: str) -> tuple[str, str]:
    if data_quality_status == "critical":
        return "데이터 참고", "down"
    if data_quality_status == "degraded":
        return "신호 점검 중", "flat"
    if "매수 관심" in hero_verdict:
        return "매수 관심", "up"
    if "리스크 주의" in hero_verdict:
        return "리스크 주의", "down"
    if "관망" in hero_verdict:
        return "관망", "flat"
    return "시장 점검", hero_tone


def _format_macro_value(item: dict[str, Any]) -> str:
    price = item.get("price")
    if price is None:
        return ""
    try:
        numeric_price = float(price)
    except (TypeError, ValueError):
        return str(price)
    if is_rate_canonical_key(str(item.get("canonical_key", ""))):
        return f"{numeric_price:.2f}%"
    return f"{numeric_price:,.2f}"


def _format_macro_change(item: dict[str, Any]) -> tuple[str, str]:
    canonical_key = str(item.get("canonical_key", ""))
    if is_rate_canonical_key(canonical_key):
        change_bps = item.get("change_bps")
        if change_bps is None:
            return "", "flat"
        numeric = float(change_bps)
        return (
            f"{numeric:+.0f}bp",
            "up" if numeric > 0 else "down" if numeric < 0 else "flat",
        )

    change_pct = item.get("change_pct")
    if change_pct is None:
        return "", "flat"
    numeric = float(change_pct)
    return (
        f"{numeric:+.2f}%",
        "up" if numeric > 0 else "down" if numeric < 0 else "flat",
    )


def _build_btc_data(packet: dict, section_3: str) -> BTCData:
    # DEPRECATED: unified-pipeline — _build_btc_data_v2(unified) 로 교체 예정
    """packet의 bitcoin 데이터로 BTCData 구성."""
    btc = packet.get("bitcoin", {})
    spot = btc.get("spot", {})
    fg_value = btc.get("fear_greed_value")
    fg_label = btc.get("fear_greed_label") or ""
    spot_price = spot.get("price")

    # ETF 포인트를 템플릿용 dict로 변환 (direction, change_pct 포맷팅)
    etf_items: list[dict] = []
    for e in btc.get("etf_points", []):
        pct = e.get("change_pct", 0) or 0
        etf_items.append(
            {
                "ticker": e.get("ticker", e.get("label", "")),
                "price": e.get("price", 0),
                "change_pct": f"{pct:+.2f}%",
                "direction": "up" if pct > 0 else "down" if pct < 0 else "flat",
                "volume": _format_volume(e.get("daily_volume", 0) or 0),
            }
        )

    # 기관 보유 현황: 모델 필드명 → 템플릿 필드명 매핑
    official_snapshots: list[dict] = []
    for snap in btc.get("official_etf_snapshots", []):
        official_snapshots.append(
            {
                "issuer": snap.get("issuer", ""),
                "ticker": snap.get("ticker", ""),
                "btc_held": f"{snap.get('total_btc', 0):,.0f}",
                "aum": f"${snap.get('aum_usd', 0):,.0f}",
            }
        )

    spot_change, spot_direction = _format_pct_badge(spot.get("change_pct"))
    status_text = ""
    if spot_price is None and fg_value is None:
        status_text = "이번 집계에서는 BTC 핵심값을 확인하지 못했어요."
    elif spot_price is None:
        status_text = "BTC 현물가는 이번 집계에서는 확인되지 않았어요."
    elif fg_value is None:
        status_text = "공포탐욕지수는 이번 집계에서는 확인되지 않았어요."

    return BTCData(
        spot_price=f"${float(spot_price):,.0f}"
        if spot_price is not None
        else "이번 집계에서는 확인되지 않았어요",
        spot_change=spot_change if spot_price is not None else "",
        spot_direction=spot_direction,
        fear_greed_value=int(fg_value) if fg_value is not None else 0,
        fear_greed_label=fg_label or "이번 집계에서는 확인되지 않았어요",
        etf_items=etf_items,
        official_snapshots=official_snapshots,
        official_total_btc=(
            f"{float(btc.get('official_etf_total_btc')):,.2f} BTC"
            if btc.get("official_etf_total_btc") is not None
            else ""
        ),
        official_total_aum=(
            f"${float(btc.get('official_etf_total_aum_usd')):,.0f}"
            if btc.get("official_etf_total_aum_usd") is not None
            else ""
        ),
        status_text=status_text,
    )


def _build_btc_data_v2(unified: "UnifiedOutput") -> BTCData:
    """QuantitativeLayer 기반 BTCData 생성 (v2).

    unified-pipeline: unified.quantitative.btc_* 필드를 직접 소비.
    FC-2: btc_total_holding (소수 2자리), FC-3: btc_spot.value_fmt ($형식).
    official_snapshots: QuantitativeLayer.btc_etf_issuers 에서 채움.
    etf_items(live ETF 가격): QuantitativeLayer 미포함 → 빈 리스트 유지.
    """
    q = unified.quantitative
    btc = q.btc_spot

    status_text = ""
    if btc is None and q.btc_fear_greed_value is None:
        status_text = "이번 집계에서는 BTC 핵심값을 확인하지 못했어요."
    elif btc is None:
        status_text = "BTC 현물가는 이번 집계에서는 확인되지 않았어요."
    elif q.btc_fear_greed_value is None:
        status_text = "공포탐욕지수는 이번 집계에서는 확인되지 않았어요."

    return BTCData(
        spot_price=btc.value_fmt if btc is not None else "이번 집계에서는 확인되지 않았어요",
        spot_change=btc.change if btc is not None else "",
        spot_direction=btc.trend if btc is not None else "flat",
        fear_greed_value=q.btc_fear_greed_value if q.btc_fear_greed_value is not None else 0,
        fear_greed_label=q.btc_fear_greed_label or "이번 집계에서는 확인되지 않았어요",
        etf_items=[],  # live ETF price points — QuantitativeLayer 미포함
        official_snapshots=[
            {
                "issuer": p.issuer,
                "ticker": p.ticker,
                "btc_held": p.btc_held or "",
                "aum": p.aum or "",
            }
            for p in q.btc_etf_issuers
        ],
        official_total_btc=q.btc_total_holding or "",
        official_total_aum=q.btc_total_aum_usd or "",
        status_text=status_text,
    )


def _format_subject_date(packet: dict) -> str:
    """packet에서 날짜를 추출하여 '3/18 화' 형식으로 반환."""
    import datetime

    date_str = packet.get("date", "")
    if date_str:
        try:
            dt = datetime.date.fromisoformat(date_str)
            return f"{dt.month}/{dt.day} {_DAY_NAMES[dt.weekday()]}"
        except (ValueError, IndexError):
            pass
    return ""


def _extract_index_change(packet: dict, ticker: str) -> str:
    """packet에서 특정 지수의 등락을 추출."""
    for idx in packet.get("us_indices", []):
        if idx.get("ticker") == ticker:
            change = idx.get("change_pct", 0)
            label = "S&P" if ticker == "SPY" else "나스닥" if ticker == "QQQ" else ticker
            return f"{label} {change:+.1f}%"
    return ""


def _extract_btc_price(packet: dict) -> str:
    """packet에서 BTC 가격을 추출."""
    btc = packet.get("bitcoin", {})
    price = btc.get("spot", {}).get("price", 0)
    return f"BTC ${price:,.0f}" if price else ""


def _extract_key_event(section_map: SectionMap) -> str:
    """Section 6에서 가장 영향도 높은 이벤트를 추출."""
    events = parse_event_calendar(section_map.get("section_6", ""))
    if events:
        today_events = [e for e in events if e["is_today"]]
        target = today_events[0] if today_events else events[0]
        return target["name"][:20]
    return ""


def _build_subject_line(section_map: SectionMap, packet: dict) -> str:
    """[날짜 요일] 브리핑 — [지수 등락] · [BTC 가격] · [핵심 변수]"""
    date_str = _format_subject_date(packet)
    sp500_change = _extract_index_change(packet, "SPY")
    btc_price = _extract_btc_price(packet)
    key_event = _extract_key_event(section_map)

    parts = [p for p in [sp500_change, btc_price, key_event] if p]
    subject = f"{date_str} 브리핑 — {' · '.join(parts)}" if parts else f"{date_str} 브리핑"

    if packet.get("data_quality", {}).get("status") == "critical":
        subject = f"[데이터 참고] {subject}"

    return subject


def _build_preheader(badges: list[dict], section_map: SectionMap) -> str:
    """preheader 텍스트 생성."""
    parts = [
        f"{badge['label']} {badge['value']}"
        if badge.get("value") != "확인 중"
        else f"{badge['label']} 확인 중"
        for badge in badges[:3]
    ]
    return " · ".join(parts)[:140]


def _format_display_date_v2(packet: dict) -> str:
    """packet에서 표시용 날짜 생성."""
    import datetime as _dt

    # 1) 명시적 date 키
    date_str = packet.get("date", "")
    if date_str:
        try:
            dt = _dt.date.fromisoformat(date_str)
            return f"{dt.year}년 {dt.month}월 {dt.day}일 {_DAY_NAMES[dt.weekday()]}요일"
        except (ValueError, IndexError):
            pass
    # 2) generated_at_utc ISO 타임스탬프 폴백
    gen_str = packet.get("generated_at_utc", "")
    if gen_str:
        try:
            dt2 = _dt.datetime.fromisoformat(gen_str)
            from zoneinfo import ZoneInfo

            kst = dt2.astimezone(ZoneInfo("Asia/Seoul"))
            return f"{kst.year}년 {kst.month}월 {kst.day}일 {_DAY_NAMES[kst.weekday()]}요일"
        except (ValueError, IndexError):
            pass
    return ""


def _parse_macro_indicators(section_1: str) -> list[MacroIndicator]:
    # DEPRECATED: unified-pipeline — LLM 텍스트 regex 파싱 제거 대상
    # 기존 로직은 _macro_indicators_from_packet(packet) 폴백으로 대체됨
    # (호출자 _build_email_context_v2 의 폴백 분기가 처리)
    return []
    # --- 이하 기존 로직 (주석 처리) ---
    # indicators: list[MacroIndicator] = []
    # if not section_1.strip():
    #     return indicators
    #
    # indicator_re = re.compile(r"(.+?):\s*(.+?)\s*\((.+?)\)")
    # for line in section_1.splitlines():
    #     stripped = line.strip().lstrip("- ")
    #     if not stripped:
    #         continue
    #     match = indicator_re.match(stripped)
    #     if match:
    #         label = match.group(1).strip()
    #         value = match.group(2).strip()
    #         change = match.group(3).strip()
    #         is_prev = "(전일" in stripped or "전일 값" in stripped
    #         is_anom = "anomaly" in stripped.lower() or value == "—"
    #         direction = "flat"
    #         if change.startswith("+"):
    #             direction = "up"
    #         elif change.startswith("-"):
    #             direction = "down"
    #         indicators.append(
    #             MacroIndicator(
    #                 label=label,
    #                 value=value,
    #                 change=change,
    #                 direction=direction,
    #                 is_previous=is_prev,
    #                 is_anomaly=is_anom,
    #                 status_text=None,
    #             )
    #         )
    # return indicators


def _parse_stocks(section_2: str) -> tuple[list[StockItem], list[StockItem]]:
    # DEPRECATED: unified-pipeline — LLM 텍스트 regex 파싱 제거 대상
    # 기존 로직은 _stock_indices_from_packet / _stock_tech_from_packet 폴백으로 대체됨
    return [], []
    # --- 이하 기존 로직 (주석 처리) ---
    # indices: list[StockItem] = []
    # tech: list[StockItem] = []
    # if not section_2.strip():
    #     return indices, tech
    #
    # in_tech = False
    # stock_re = re.compile(r"(\w+)\s+\$?([\d,.]+)\s*([+-][\d.]+%)")
    # for line in section_2.splitlines():
    #     stripped = line.strip()
    #     if "빅테크" in stripped or "Big Tech" in stripped.lower():
    #         in_tech = True
    #         continue
    #     match = stock_re.search(stripped)
    #     if match:
    #         ticker = match.group(1)
    #         price = match.group(2)
    #         change_pct = match.group(3)
    #         direction = (
    #             "up"
    #             if change_pct.startswith("+")
    #             else "down"
    #             if change_pct.startswith("-")
    #             else "flat"
    #         )
    #         item = StockItem(
    #             ticker=ticker,
    #             name=ticker,
    #             price=price,
    #             change_pct=change_pct,
    #             direction=direction,
    #             volume=None,
    #         )
    #         if in_tech:
    #             tech.append(item)
    #         else:
    #             indices.append(item)
    # return indices, tech


def _parse_issue_briefings(section_4_1: str) -> list[dict]:
    """Section 4-1 이슈 브리핑을 딕셔너리 리스트로 파싱."""
    if not section_4_1.strip():
        return []
    briefings: list[dict] = []
    current_topic = ""
    current_lines: list[str] = []

    for line in section_4_1.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_topic and current_lines:
                briefings.append({"topic": current_topic, "body": "\n".join(current_lines).strip()})
                current_topic = ""
                current_lines = []
            continue
        if not current_topic:
            current_topic = stripped
        else:
            current_lines.append(stripped)

    if current_topic and current_lines:
        briefings.append({"topic": current_topic, "body": "\n".join(current_lines).strip()})
    return briefings


def _parse_sonar(section_5_2: str) -> list[dict] | None:
    """Section 5-2 Sonar 교차 분석을 딕셔너리 리스트로 파싱."""
    if not section_5_2.strip():
        return None
    analyses: list[dict] = []
    current_lines: list[str] = []

    for line in section_5_2.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_lines:
                analyses.append({"body": "\n".join(current_lines).strip()})
                current_lines = []
            continue
        current_lines.append(stripped)

    if current_lines:
        analyses.append({"body": "\n".join(current_lines).strip()})
    return analyses[:3] if analyses else None


def _split_hero(raw: str) -> tuple[str, list[str]]:
    """section_0 텍스트를 (첫 문장, 나머지 문장 리스트)로 분리."""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if not lines:
        return "", []
    return lines[0], lines[1:]


def _stock_indices_from_packet(packet: dict) -> list[StockItem]:
    """packet['us_indices']에서 주요 지수 StockItem 리스트 생성."""
    _LABEL = {"SPY": "S&P 500", "QQQ": "나스닥"}
    items: list[StockItem] = []
    for idx in packet.get("us_indices", []):
        ticker = idx.get("ticker", "")
        if ticker not in _LABEL:
            continue
        pct = idx.get("change_pct", 0) or 0
        price = idx.get("price", 0) or 0
        items.append(
            StockItem(
                ticker=ticker,
                name=_LABEL[ticker],
                price=f"{price:,.2f}" if price else "",
                change_pct=f"{pct:+.2f}%",
                direction="up" if pct > 0 else "down" if pct < 0 else "flat",
                volume=None,
            )
        )
    return items


def _stock_tech_from_packet(packet: dict) -> list[StockItem]:
    """packet['tech_stocks']에서 빅테크 StockItem 리스트 생성."""
    items: list[StockItem] = []
    for s in packet.get("tech_stocks", []):
        ticker = s.get("ticker", "")
        pct = s.get("change_pct", 0) or 0
        items.append(
            StockItem(
                ticker=ticker,
                name=s.get("label", ticker),
                price="",
                change_pct=f"{pct:+.2f}%",
                direction="up" if pct > 0 else "down" if pct < 0 else "flat",
                volume=None,
            )
        )
    return items


def _macro_indicators_from_packet(packet: dict) -> list[MacroIndicator]:
    """packet['macro'] 리스트에서 MacroIndicator 리스트 생성."""
    items: list[MacroIndicator] = []
    macro_list = packet.get("macro", [])
    if not isinstance(macro_list, list):
        return items
    for m in macro_list:
        label = m.get("label", "")
        if m.get("price") is None and m.get("validation_status") != "anomaly":
            continue
        change_str, direction = _format_macro_change(m)
        items.append(
            MacroIndicator(
                label=label,
                value=_format_macro_value(m),
                change=change_str,
                direction=direction,
                is_previous=m.get("is_previous_value", False),
                is_anomaly=m.get("validation_status", "ok") != "ok",
                status_text=str(m.get("resolution_reason", "") or ""),
            )
        )
    return items


def _prepare_v2_news_items(section_4_2: str) -> list[dict[str, object]]:
    # DEPRECATED: unified-pipeline — _prepare_v2_news_items_from_unified(unified) 로 교체 예정
    prepared: list[dict[str, object]] = []
    for item in parse_news_items(section_4_2):
        safe_url = _safe_link(item.get("source_url") or "")
        prepared.append(
            {
                **item,
                "source_url": safe_url,
                "source_name": _display_source_name(item.get("source_name"), safe_url),
                "source_kind": _source_kind(item.get("source_name"), safe_url),
                "source_label": _news_source_label(item.get("source_name"), safe_url),
            }
        )
    return prepared


def _prepare_v2_news_items_from_unified(unified: "UnifiedOutput") -> list[dict[str, object]]:
    """NarrativeLayer 기반 뉴스 아이템 생성 (v2).

    unified-pipeline: unified.narrative.news 직접 소비.
    """
    prepared: list[dict[str, object]] = []
    for item in unified.narrative.news:
        if not isinstance(item, dict):
            continue
        safe_url = _safe_link(item.get("source_url") or "")
        prepared.append(
            {
                **item,
                "source_url": safe_url,
                "source_name": _display_source_name(item.get("source_name"), safe_url),
                "source_kind": _source_kind(item.get("source_name"), safe_url),
                "source_label": _news_source_label(item.get("source_name"), safe_url),
            }
        )
    return prepared


def _to_email_news_item(item: dict[str, object]) -> _EmailNewsItem:
    safe_url_value = item.get("source_url")
    source_name_value = item.get("source_name")
    safe_url = safe_url_value if isinstance(safe_url_value, str) else None
    source_name = source_name_value if isinstance(source_name_value, str) else None
    return _EmailNewsItem(
        headline=str(item["headline"]),
        market_meaning=str(item.get("body") or ""),
        korea_takeaway=str(item.get("tldr") or ""),
        url=str(item.get("source_url") or ""),
        safe_url=safe_url,
        source_name=source_name,
    )


def _build_email_context_v2(
    subject: str,
    body: str,
    packet: dict,
    *,
    unsubscribe_url: str | None = None,
    unified: "UnifiedOutput | None" = None,
) -> dict[str, object]:
    """새 섹션 구조 기반 이메일 컨텍스트 빌드."""
    section_map = extract_sections(body)

    snapshot_badges = (
        _build_snapshot_badges_v2(unified)
        if unified is not None
        else _build_snapshot_badges(packet)
    )
    news_items = (
        _prepare_v2_news_items_from_unified(unified)
        if unified is not None
        else _prepare_v2_news_items(section_map.get("section_4_2", ""))
    )
    sector_mapping = (
        unified.narrative.sector_mapping
        if unified is not None and unified.narrative.sector_mapping is not None
        else parse_sector_mapping(section_map.get("section_4_3", ""))
    )
    btc_data = (
        _build_btc_data_v2(unified)
        if unified is not None
        else _build_btc_data(packet, section_map.get("section_3", ""))
    )
    events = parse_event_calendar(section_map.get("section_6", ""))
    event_calendar = events if events else None
    macro_indicators = _parse_macro_indicators(section_map.get("section_1", ""))
    stock_indices, stock_tech = _parse_stocks(section_map.get("section_2", ""))

    # 시장 지표 폴백: LLM 섹션 파싱이 비어있으면 packet 데이터에서 직접 구성
    if not stock_indices:
        log_structured(
            logger,
            event="fallback.used",
            message="briefing 파싱 결과가 비어 packet 값으로 stock_indices를 보강했어요.",
            level=logging.WARNING,
            field="stock_indices",
            source="packet_fallback",
        )
        stock_indices = _stock_indices_from_packet(packet)
    if not stock_tech:
        log_structured(
            logger,
            event="fallback.used",
            message="briefing 파싱 결과가 비어 packet 값으로 stock_tech를 보강했어요.",
            level=logging.WARNING,
            field="stock_tech",
            source="packet_fallback",
        )
        stock_tech = _stock_tech_from_packet(packet)
    if not macro_indicators:
        log_structured(
            logger,
            event="fallback.used",
            message="briefing 파싱 결과가 비어 packet 값으로 macro_indicators를 보강했어요.",
            level=logging.WARNING,
            field="macro_indicators",
            source="packet_fallback",
        )
        macro_indicators = _macro_indicators_from_packet(packet)

    dq = packet.get("data_quality", {})
    data_quality_status = dq.get("status", "ok")
    footer_notes = packet.get("data_footer_notes", [])

    final_subject = _build_subject_line(section_map, packet) if not subject else subject

    hero_context = _build_hero_context(section_map.get("section_0", ""))
    header_signal_label, header_signal_tone = _header_signal(
        str(hero_context["hero_verdict"]),
        str(hero_context["hero_tone"]),
        str(data_quality_status),
    )
    news_source_items = _build_news_source_items(
        [_to_email_news_item(item) for item in news_items],
        [],
    )

    return {
        "subject": final_subject,
        "preheader": _build_preheader(snapshot_badges, section_map),
        "display_date": _format_display_date_v2(packet),
        "read_time": "3분 읽기",
        "snapshot_badges": snapshot_badges,
        "header_signal_label": header_signal_label,
        "header_signal_tone": header_signal_tone,
        **hero_context,
        "macro_indicators": macro_indicators,
        "stock_indices": stock_indices,
        "stock_tech": stock_tech,
        "btc_data": btc_data,
        "news_status_text": "이번 집계에서는 주요 뉴스를 확인하지 못했어요."
        if not news_items
        else "",
        "market_status_text": (
            "이번 집계에서는 시장 지표를 확인하지 못했어요."
            if not stock_indices and not stock_tech and not macro_indicators
            else ""
        ),
        "issue_briefings": (
            unified.narrative.issue_briefings
            if unified is not None and unified.narrative.issue_briefings is not None
            else _parse_issue_briefings(section_map.get("section_4_1", ""))
        ),
        "news_items": news_items,
        "news_source_items": news_source_items,
        "market_source_lines": _market_source_lines(),
        "sector_mapping": sector_mapping,
        "weekly_context": (
            unified.narrative.weekly_context
            if unified is not None and unified.narrative.weekly_context is not None
            else section_map.get("section_5_1", "")
        ),
        "sonar_analyses": (
            unified.narrative.sonar_analyses
            if unified is not None and unified.narrative.sonar_analyses is not None
            else _parse_sonar(section_map.get("section_5_2", ""))
        ),
        "x_reactions": section_map.get("section_5_3", "") or None,
        "event_calendar": (
            unified.narrative.event_calendar
            if unified is not None and unified.narrative.event_calendar is not None
            else event_calendar
        ),
        "data_quality_status": data_quality_status,
        "footer_notes": footer_notes if data_quality_status != "ok" else [],
        "unsubscribe_url": unsubscribe_url or "",
        "github_url": PROJECT_GITHUB_URL,
    }


def _direction_color(direction: str) -> str:
    if direction == "up":
        return "#16a34a"
    if direction == "down":
        return "#dc2626"
    if direction in {"flat", "mixed"}:
        return "#64748b"
    return "#0f172a"


def _percent_direction(token: str) -> str | None:
    normalized = token.replace(",", "").strip()
    sign = ""
    if normalized.startswith("+"):
        sign = "+"
    elif normalized.startswith("-"):
        sign = "-"

    try:
        value = float(normalized.lstrip("+-").rstrip("%"))
    except ValueError:
        return None

    if abs(value) < 1e-9:
        return "flat"
    if sign == "+":
        return "up"
    if sign == "-":
        return "down"
    return None


def _token_direction(text: str) -> str | None:
    up_count = sum(text.count(token) for token in UP_TOKENS)
    down_count = sum(text.count(token) for token in DOWN_TOKENS)
    flat_count = sum(text.count(token) for token in FLAT_TOKENS)

    if up_count > down_count and up_count > 0:
        return "up"
    if down_count > up_count and down_count > 0:
        return "down"
    if flat_count > 0 and up_count == 0 and down_count == 0:
        return "flat"
    return None


def _highlight_metric_text(text: str, default_direction: str) -> str:
    parts: list[str] = []
    last_index = 0

    for match in PERCENT_RE.finditer(text):
        start, end = match.span()
        token = match.group(0)
        token_direction = _percent_direction(token)
        if token_direction is None:
            token_direction = (
                default_direction if default_direction in {"up", "down", "flat"} else "neutral"
            )
        color = _direction_color(token_direction)
        parts.append(html.escape(text[last_index:start]))
        display_token = _display_percent_token(token)
        parts.append(
            f'<span style="color:{color};font-weight:700;">{html.escape(display_token)}</span>'
        )
        last_index = end

    if not parts:
        return html.escape(text)

    parts.append(html.escape(text[last_index:]))
    return "".join(parts)


def _render_body_line(text: str) -> str:
    highlighted = _highlight_metric_text(
        text, default_direction=_token_direction(text) or "neutral"
    )
    return highlighted if highlighted != html.escape(text) else html.escape(text)


def render_briefing_email_html(
    subject: str,
    body: str,
    *,
    unsubscribe_url: str | None = None,
    packet: dict | None = None,
    unified: "UnifiedOutput | None" = None,
) -> str:
    environment = _load_email_environment()
    template = environment.get_template("email_base.html.j2")
    context = _build_email_context_v2(
        subject=subject,
        body=body,
        packet=packet or {},
        unsubscribe_url=unsubscribe_url,
        unified=unified,
    )
    return template.render(**context).strip()


def render_briefing_email_text(
    subject: str,
    body: str,
    *,
    unsubscribe_url: str | None = None,
    packet: dict | None = None,
    unified: "UnifiedOutput | None" = None,
) -> str:
    environment = _load_email_environment()
    template = environment.get_template("email_v2.txt.j2")
    context = _build_email_context_v2(
        subject=subject,
        body=body,
        packet=packet or {},
        unsubscribe_url=unsubscribe_url,
        unified=unified,
    )
    return template.render(**context).strip()


def build_briefing_message(
    *,
    subject: str,
    body: str,
    sender: str,
    recipient: str,
    unsubscribe_url: str,
    packet: dict | None = None,
    unified: "UnifiedOutput | None" = None,
) -> MIMEMultipart:
    html_body = render_briefing_email_html(
        subject=subject,
        body=body,
        unsubscribe_url=unsubscribe_url,
        packet=packet,
        unified=unified,
    )
    text_body = render_briefing_email_text(
        subject=subject,
        body=body,
        unsubscribe_url=unsubscribe_url,
        packet=packet,
        unified=unified,
    )
    msg = MIMEMultipart("alternative")
    msg["to"] = recipient
    msg["from"] = sender
    msg["subject"] = subject
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.attach(MIMEText(text_body, _subtype="plain", _charset="utf-8"))
    msg.attach(MIMEText(html_body, _subtype="html", _charset="utf-8"))
    return msg


class GmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _subscription_repository(self) -> SubscriptionRepository:
        return SupabaseSubscriptionRepository(
            supabase_url=self.settings.supabase_url,
            service_role_key=self.settings.supabase_service_role_key,
        )

    def _load_credentials(self) -> Credentials:
        Request, CredentialsType, InstalledAppFlow, _ = _gmail_dependencies()
        creds: Credentials | None = None
        if self.settings.gmail_token_file.exists():
            try:
                creds = CredentialsType.from_authorized_user_file(
                    str(self.settings.gmail_token_file), SCOPES
                )
            except Exception as exc:
                log_structured(
                    logger,
                    event="error.raised",
                    message="토큰 파일을 읽는 중 문제가 있어 다시 인증이 필요해요.",
                    level=logging.WARNING,
                    provider="gmail",
                    reason=str(exc),
                    error_type=type(exc).__name__,
                )

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.settings.gmail_token_file.write_text(creds.to_json(), encoding="utf-8")
            return creds

        if not self.settings.gmail_oauth_interactive:
            raise RuntimeError(
                "No valid Gmail token found. Set GMAIL_OAUTH_INTERACTIVE=true for local OAuth login, "
                "or provide a pre-generated token.json in CI."
            )

        if not self.settings.gmail_credentials_file.exists():
            raise FileNotFoundError(
                f"Gmail credentials file not found: {self.settings.gmail_credentials_file}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.settings.gmail_credentials_file),
            SCOPES,
        )
        creds = flow.run_local_server(port=0)

        self.settings.gmail_token_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings.gmail_token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def send(
        self,
        subject: str,
        body: str,
        *,
        packet: dict | None = None,
        unified: "UnifiedOutput | None" = None,
    ) -> None:
        if not self.settings.send_email:
            log_structured(
                logger,
                event="phase.skip",
                message="SEND_EMAIL=false라서 메일 발송은 건너뛸게요.",
                provider="gmail",
                reason="send_email_disabled",
            )
            return

        if not self.settings.gmail_sender:
            raise ValueError("GMAIL_SENDER is required when SEND_EMAIL=true")

        recipients = self._subscription_repository().list_active_recipients(
            self.settings.subscription_newsletter_key
        )
        if not recipients:
            log_structured(
                logger,
                event="phase.skip",
                message="active 구독자가 없어 메일 발송을 건너뛸게요.",
                provider="gmail",
                reason="no_active_subscribers",
            )
            return

        creds = self._load_credentials()
        _, _, _, build = _gmail_dependencies()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        sent_count = 0
        failures: list[str] = []
        for recipient in recipients:
            unsubscribe_url = _unsubscribe_url(
                settings=self.settings,
                recipient=recipient,
            )
            msg = build_briefing_message(
                subject=subject,
                body=body,
                sender=self.settings.gmail_sender,
                recipient=recipient.email,
                unsubscribe_url=unsubscribe_url,
                packet=packet,
                unified=unified,
            )
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            try:
                service.users().messages().send(userId="me", body={"raw": raw}).execute()
                sent_count += 1
                log_structured(
                    logger,
                    event="publish.delivered",
                    message="구독자에게 브리핑 메일을 보냈어요.",
                    provider="gmail",
                    recipient=recipient.email,
                    mail_intent="newsletter",
                )
            except Exception as exc:
                failures.append(recipient.email)
                log_structured(
                    logger,
                    event="error.raised",
                    message="구독자별 메일 발송 중 일부 실패가 발생했어요.",
                    level=logging.ERROR,
                    provider="gmail",
                    recipient=recipient.email,
                    reason=str(exc),
                    error_type=type(exc).__name__,
                )

        if failures:
            raise RuntimeError(
                f"Failed to send newsletter to {len(failures)} recipients: {', '.join(failures)}"
            )

        log_structured(
            logger,
            event="publish.complete",
            message="브리핑 메일을 보냈어요.",
            provider="gmail",
            kept_count=sent_count,
        )
