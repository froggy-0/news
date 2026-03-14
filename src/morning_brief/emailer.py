from __future__ import annotations

import base64
import html
import logging
import re
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

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

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

logger = logging.getLogger(__name__)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PERCENT_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%")
UP_TOKENS = ("올랐", "상승", "강세", "반등", "높아졌", "증가", "확대", "유입", "개선", "회복")
DOWN_TOKENS = ("내렸", "하락", "약세", "밀렸", "낮아졌", "감소", "축소", "유출", "둔화", "후퇴")
FLAT_TOKENS = ("보합", "유지", "비슷", "변동이 크지", "큰 변화는 없")
EMAIL_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
PROJECT_GITHUB_URL = "https://github.com/froggy-0/news"
DEFAULT_UNSUBSCRIBE_EMAIL = "unsubscribe@example.com"
NONE_LIKE_TEXTS = {"", "none", "null", "n/a", "na"}

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials
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
    interpretation: str
    url: str
    safe_url: str | None
    source_label: str | None


@dataclass(frozen=True)
class _EmailBriefRow:
    name: str
    change_text: str
    context_text: str
    context_html: Markup
    tone: str


@dataclass(frozen=True)
class _EmailSourceItem:
    label: str
    url: str
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


def _split_recipients(raw: str) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for part in raw.replace("\n", ",").split(","):
        candidate = part.strip()
        if not candidate:
            continue
        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        recipients.append(candidate)
    return recipients


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
    return f"{year}.{month}.{day} {weekday}".strip()


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


def _source_label(url: str | None) -> str | None:
    if not url:
        return None

    safe_url = _safe_link(url)
    if safe_url is None:
        return None

    parsed = urlparse(safe_url)
    hostname = parsed.netloc.lower()
    if not hostname:
        return None

    if hostname.startswith("www."):
        hostname = hostname[4:]

    if hostname.endswith("twitter.com"):
        hostname = "x.com"

    if hostname == "x.com":
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            return f"x.com/{path_parts[0]}"
        return hostname

    return hostname


def _sanitize_optional_text(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    if normalized.lower() in NONE_LIKE_TEXTS:
        return ""
    return normalized


def _parse_news_metric_line(line: str) -> tuple[str, str, str | None]:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) >= 3 and _safe_link(parts[-1] or ""):
        headline = " | ".join(parts[:-2]).strip()
        interpretation = _sanitize_optional_text(parts[-2].strip())
        source_url = parts[-1].strip()
        return headline or line.strip(), interpretation, source_url or None
    if len(parts) == 2:
        return (
            parts[0].strip() or line.strip(),
            _sanitize_optional_text(parts[1].strip()),
            None,
        )
    if len(parts) >= 3:
        return (
            parts[0].strip() or line.strip(),
            _sanitize_optional_text(" | ".join(parts[1:])),
            None,
        )
    return line.strip(), "", None


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
        interpretations = [
            _first_sentence(important_news.groups["conclusion"][1]),
            _first_sentence(important_news.groups["insight"][1]),
            _first_sentence(important_news.groups["watch"][1]),
        ]
        fallback_interpretation = next((item for item in interpretations if item), "")
        for index, line in enumerate(
            _first_metric_lines(important_news.groups["metrics"][1], limit=limit)
        ):
            headline, interpretation, source_url = _parse_news_metric_line(line)
            safe_url = _safe_link(source_url or "")
            if safe_url is None and index < len(safe_reference_urls):
                safe_url = safe_reference_urls[index]
            items.append(
                _EmailNewsItem(
                    headline=headline,
                    interpretation=_sanitize_optional_text(
                        interpretation or fallback_interpretation
                    ),
                    url=safe_url or "",
                    safe_url=safe_url,
                    source_label=_source_label(safe_url),
                )
            )

    if items:
        return items[:limit]

    for index, section in enumerate(sections[:limit]):
        safe_url = safe_reference_urls[index] if index < len(safe_reference_urls) else None
        interpretation = _first_sentence(section.groups["conclusion"][1]) or _first_sentence(
            section.groups["insight"][1]
        )
        items.append(
            _EmailNewsItem(
                headline=section.heading,
                interpretation=_sanitize_optional_text(
                    interpretation or _first_non_empty_paragraph(section.content)
                ),
                url=safe_url or "",
                safe_url=safe_url,
                source_label=_source_label(safe_url),
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
    cleaned = re.split(r"(은|는|이|가)\s*$", prefix)[0].strip()
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
            return (
                f"비트코인은 전일 대비 {abs_change} {verb}, 현재 {price_match.group(1)}달러입니다."
            )
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
        fallback_heading = layer_three_section.heading
        for line in candidate_lines[:limit]:
            row = _build_stock_row(line, fallback_heading)
            if row is None:
                continue
            if row.context_text in seen_contexts:
                continue
            seen_contexts.add(row.context_text)
            rows.append(row)
            if len(rows) >= limit:
                return rows
        return rows

    for section in sections:
        candidate_lines = [
            *_first_metric_lines(section.groups["metrics"][1], limit=limit),
            *_first_metric_lines(section.groups["watch"][1], limit=limit),
        ]
        for line in candidate_lines:
            row = _build_stock_row(line, section.heading)
            if row is None:
                continue
            if row.context_text in seen_contexts:
                continue
            seen_contexts.add(row.context_text)
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _split_macro_line(line: str) -> tuple[str, str]:
    normalized_line = _strip_inline_source(line)
    if "는 " in normalized_line:
        label, value = normalized_line.split("는 ", 1)
    elif "은 " in normalized_line:
        label, value = normalized_line.split("은 ", 1)
    else:
        return "거시 지표", normalized_line
    return label.strip() or "거시 지표", value.strip() or normalized_line


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
    seen: set[str] = set()

    for item in news_items:
        safe_url = item.safe_url
        if not safe_url or safe_url in seen:
            continue
        seen.add(safe_url)
        items.append(_EmailSourceItem(label=item.headline, url=safe_url, safe_url=safe_url))

    for item in reference_items:
        safe_url = item.get("safe_url")
        if not isinstance(safe_url, str) or not safe_url or safe_url in seen:
            continue
        seen.add(safe_url)
        items.append(
            _EmailSourceItem(
                label=str(item.get("label") or safe_url),
                url=safe_url,
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


def _unsubscribe_url(sender: str) -> str:
    target = sender.strip() or DEFAULT_UNSUBSCRIBE_EMAIL
    subject = quote("Morning Market Brief 구독 해지")
    body = quote("구독 해지를 요청합니다.")
    return f"mailto:{target}?subject={subject}&body={body}"


def _primary_cta(reference_items: list[dict[str, str | None]]) -> dict[str, str]:
    first_reference = next(
        (
            item
            for item in reference_items
            if isinstance(item.get("safe_url"), str) and item["safe_url"]
        ),
        None,
    )
    if first_reference is not None:
        return {"label": "대표 출처 열기", "url": str(first_reference["safe_url"])}
    return {"label": "GitHub에서 보기", "url": PROJECT_GITHUB_URL}


def _build_email_context(subject: str, body: str, *, sender: str = "") -> dict[str, object]:
    body_without_references, references = _split_reference_block(body)
    main_body, footer_notes = _split_footer_note_block(body_without_references)
    title, notice, sections = _extract_brief_structure(main_body)
    parsed_sections = _build_email_sections(sections)
    layer_two_section = _find_layer_section(
        parsed_sections,
        exact_heading="중요한 뉴스",
    ) or _find_layer_section(parsed_sections, contains_heading="LAYER 2")
    layer_three_section = _find_layer_section(parsed_sections, contains_heading="LAYER 3")
    display_date = _format_display_date(title=title, subject=subject)
    layer_one_text = _extract_layer_one_text(parsed_sections, notice, title)
    reference_items = _build_reference_items(references)
    news_items = _build_news_items(parsed_sections, references)
    stock_rows = _build_stock_rows(parsed_sections)
    macro_rows = _build_macro_rows(parsed_sections)
    news_source_items = _build_news_source_items(news_items, reference_items)

    return {
        "subject": subject,
        "title": title,
        "display_date": display_date,
        "preheader": layer_one_text[:140].strip(),
        "notice": notice,
        "layer_one_text": layer_one_text,
        "layer_one_html": Markup(_render_body_line(layer_one_text)),
        "news_items": news_items,
        "news_fallback_text": "" if news_items else _fallback_section_text(layer_two_section),
        "stock_rows": stock_rows,
        "stock_fallback_text": "" if stock_rows else _fallback_section_text(layer_three_section),
        "macro_rows": macro_rows,
        "footer_notes": footer_notes,
        "reference_items": reference_items,
        "news_source_items": news_source_items,
        "market_source_lines": _market_source_lines(),
        "primary_cta": _primary_cta(reference_items),
        "unsubscribe_url": _unsubscribe_url(sender),
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
        parts.append(f'<span style="color:{color};font-weight:700;">{html.escape(token)}</span>')
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


def render_briefing_email_html(subject: str, body: str, *, sender: str = "") -> str:
    environment = _load_email_environment()
    template = environment.get_template("email.html.j2")
    context = _build_email_context(subject=subject, body=body, sender=sender)
    return template.render(**context).strip()


def render_briefing_email_text(subject: str, body: str, *, sender: str = "") -> str:
    environment = _load_email_environment()
    template = environment.get_template("email.txt.j2")
    context = _build_email_context(subject=subject, body=body, sender=sender)
    return template.render(**context).strip()


def build_briefing_message(
    *,
    subject: str,
    body: str,
    sender: str,
    recipients: list[str],
) -> MIMEMultipart:
    html_body = render_briefing_email_html(subject=subject, body=body, sender=sender)
    text_body = render_briefing_email_text(subject=subject, body=body, sender=sender)
    msg = MIMEMultipart("alternative")
    msg["to"] = recipients[0] if len(recipients) == 1 else sender
    if len(recipients) > 1:
        msg["bcc"] = ", ".join(recipients)
    msg["from"] = sender
    msg["subject"] = subject
    msg.attach(MIMEText(text_body, _subtype="plain", _charset="utf-8"))
    msg.attach(MIMEText(html_body, _subtype="html", _charset="utf-8"))
    return msg


class GmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _load_credentials(self) -> Credentials:
        Request, CredentialsType, InstalledAppFlow, _ = _gmail_dependencies()
        creds: Credentials | None = None
        if self.settings.gmail_token_file.exists():
            try:
                creds = CredentialsType.from_authorized_user_file(
                    str(self.settings.gmail_token_file), SCOPES
                )
            except Exception as exc:
                logger.warning("토큰 파일을 읽는 중 문제가 있어 다시 인증이 필요해요: %s", exc)

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

    def send(self, subject: str, body: str) -> None:
        if not self.settings.send_email:
            logger.info("SEND_EMAIL=false라서 메일 발송은 건너뛸게요.")
            return

        recipients = _split_recipients(self.settings.gmail_recipient)
        if not self.settings.gmail_sender or not recipients:
            raise ValueError("GMAIL_SENDER and GMAIL_RECIPIENT are required when SEND_EMAIL=true")

        creds = self._load_credentials()
        _, _, _, build = _gmail_dependencies()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        msg = build_briefing_message(
            subject=subject,
            body=body,
            sender=self.settings.gmail_sender,
            recipients=recipients,
        )

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        logger.info("브리핑 메일을 %s명에게 보냈어요.", len(recipients))
