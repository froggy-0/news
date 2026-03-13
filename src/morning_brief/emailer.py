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
    url_label: str


@dataclass(frozen=True)
class _EmailBriefRow:
    name: str
    change_text: str
    context_text: str
    context_html: Markup
    tone: str


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


def _build_snapshot_rows(sections: list[_EmailSection]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for section in sections[:4]:
        metric_line = _first_metric_line(section.groups["metrics"][1])
        if metric_line:
            rows.append((section.heading, metric_line))
    return rows


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
        (section for section in sections if section.heading == "중요한 뉴스"), None
    )
    if important_news is not None:
        interpretations = [
            _first_sentence(important_news.groups["conclusion"][1]),
            _first_sentence(important_news.groups["insight"][1]),
            _first_sentence(important_news.groups["watch"][1]),
        ]
        fallback_interpretation = next((item for item in interpretations if item), "")
        for index, headline in enumerate(
            _first_metric_lines(important_news.groups["metrics"][1], limit=limit)
        ):
            safe_url = safe_reference_urls[index] if index < len(safe_reference_urls) else None
            items.append(
                _EmailNewsItem(
                    headline=headline,
                    interpretation=fallback_interpretation,
                    url=safe_url or "",
                    safe_url=safe_url,
                    url_label=safe_url or "출처 없음",
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
                interpretation=interpretation or _first_non_empty_paragraph(section.content),
                url=safe_url or "",
                safe_url=safe_url,
                url_label=safe_url or "출처 없음",
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


def _build_stock_rows(sections: list[_EmailSection], *, limit: int = 6) -> list[_EmailBriefRow]:
    rows: list[_EmailBriefRow] = []
    for section in sections:
        candidate_lines = [
            *_first_metric_lines(section.groups["metrics"][1], limit=limit),
            *_first_metric_lines(section.groups["watch"][1], limit=limit),
        ]
        for line in candidate_lines:
            percent_match = PERCENT_RE.search(line)
            if percent_match is None:
                continue
            change_text = percent_match.group(0)
            rows.append(
                _EmailBriefRow(
                    name=_stock_name_from_line(line, fallback=section.heading),
                    change_text=change_text,
                    context_text=line,
                    context_html=Markup(_render_body_line(line)),
                    tone=_row_tone(line, change_text),
                )
            )
            if len(rows) >= limit:
                return rows
    return rows


def _build_macro_rows(sections: list[_EmailSection]) -> list[tuple[str, Markup]]:
    macro_section = next((section for section in sections if section.heading == "거시 환경"), None)
    if macro_section is None:
        return []
    rows: list[tuple[str, Markup]] = []
    for line in _first_metric_lines(macro_section.groups["metrics"][1], limit=4):
        label = line.split("는 ", 1)[0].split("은 ", 1)[0].strip() or "거시 지표"
        rows.append((label, Markup(_render_body_line(line))))
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
    display_date = _format_display_date(title=title, subject=subject)
    layer_one_text = _extract_layer_one_text(parsed_sections, notice, title)
    reference_items = _build_reference_items(references)
    news_items = _build_news_items(parsed_sections, references)
    stock_rows = _build_stock_rows(parsed_sections)
    macro_rows = _build_macro_rows(parsed_sections)

    return {
        "subject": subject,
        "title": title,
        "display_date": display_date,
        "preheader": f"{display_date} | {layer_one_text}"[:140].strip(" |"),
        "notice": notice,
        "layer_one_text": layer_one_text,
        "layer_one_html": Markup(_render_body_line(layer_one_text)),
        "news_items": news_items,
        "stock_rows": stock_rows,
        "macro_rows": macro_rows,
        "footer_notes": footer_notes,
        "reference_items": reference_items,
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


def _render_metric_item(text: str) -> str:
    default_direction = _token_direction(text) or "neutral"
    return (
        '<li style="margin:0 0 12px 0;padding:0;list-style:none;">'
        f'<span style="display:inline;color:#0f172a;font-size:15px;line-height:1.75;">{_highlight_metric_text(text, default_direction)}</span>'
        "</li>"
    )


def _text_to_html_blocks(content: str) -> str:
    blocks: list[str] = []
    paragraphs = [chunk.strip() for chunk in content.split("\n\n") if chunk.strip()]

    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if lines and all(line.startswith("- ") for line in lines):
            items = "".join(_render_metric_item(line[2:].strip()) for line in lines)
            blocks.append(
                '<ul style="margin:0;padding:0;list-style:none;color:#1f2937;font-size:15px;'
                'line-height:1.75;">'
                f"{items}</ul>"
            )
            continue

        text = "<br>".join(_render_body_line(line) for line in lines)
        blocks.append(
            f'<p style="margin:0;color:#1f2937;font-size:15px;line-height:1.8;">{text}</p>'
        )

    return "".join(blocks) or (
        '<p style="margin:0;color:#1f2937;font-size:15px;line-height:1.8;">내용이 없습니다.</p>'
    )


def _preheader_text(title: str, notice: str, sections: list[_EmailSection]) -> str:
    if notice:
        return notice[:140]
    summary_lines = _build_top_summary_lines(sections)
    if summary_lines:
        return " | ".join(summary_lines)[:140]
    if sections:
        return f"{title} | {sections[0].content[:120]}".strip()
    return title


def _render_section_row(index: int, section: _EmailSection) -> str:
    conclusion_label, conclusion_content = section.groups["conclusion"]
    metrics_label, metrics_content = section.groups["metrics"]
    insight_label, insight_content = section.groups["insight"]
    watch_label, watch_content = section.groups["watch"]
    heading = section.heading
    if heading == "중요한 뉴스":
        metrics_label = "핵심 이슈"

    conclusion_block = ""
    if conclusion_content:
        conclusion_block = (
            '<div style="padding:0 0 16px 0;">'
            f'<div style="font-size:11px;line-height:1.2;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#475569;padding:0 0 8px 0;">{html.escape(conclusion_label)}</div>'
            '<div style="padding:14px 16px;border-radius:16px;background:#f8fafc;border:1px solid #e2e8f0;">'
            f"{_text_to_html_blocks(conclusion_content)}"
            "</div>"
            "</div>"
        )
    metrics_block = ""
    if metrics_content:
        metrics_block = (
            '<div style="padding:0 0 14px 0;">'
            f'<div style="font-size:11px;line-height:1.2;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;padding:0 0 10px 0;">{html.escape(metrics_label)}</div>'
            f"{_text_to_html_blocks(metrics_content)}"
            "</div>"
        )
    insight_block = ""
    if insight_content:
        insight_block = (
            '<div style="padding:0 0 14px 0;">'
            f'<div style="font-size:11px;line-height:1.2;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#0f172a;padding:0 0 10px 0;">{html.escape(insight_label)}</div>'
            f"{_text_to_html_blocks(insight_content)}"
            "</div>"
        )
    watch_block = ""
    if watch_content:
        watch_block = (
            '<div style="padding:0;">'
            f'<div style="font-size:11px;line-height:1.2;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;padding:0 0 10px 0;">{html.escape(watch_label)}</div>'
            '<div style="padding:14px 16px;border-radius:16px;background:#f8fbff;border:1px solid #dbeafe;">'
            f"{_text_to_html_blocks(watch_content)}"
            "</div>"
            "</div>"
        )
    return (
        "<tr>"
        '<td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:20px;box-shadow:0 10px 24px rgba(15,23,42,0.03);">'
        "<tr>"
        '<td style="padding:22px 24px 22px 24px;">'
        f'<div style="width:36px;height:36px;line-height:36px;text-align:center;background:#0f172a;color:#ffffff;border-radius:999px;font-size:14px;font-weight:700;">{index}</div>'
        f'<div style="font-size:20px;line-height:1.3;font-weight:700;color:#0f172a;padding:14px 0 12px 0;">{html.escape(heading)}</div>'
        f"{conclusion_block}"
        f"{metrics_block}"
        f"{insight_block}"
        f"{watch_block}"
        "</td>"
        "</tr>"
        "</table>"
        "</td>"
        "</tr>"
    )


def _render_notice_block(notice: str) -> str:
    if not notice:
        return ""
    return (
        '<tr><td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:separate;border-spacing:0;background:#fff7ed;border:1px solid #fed7aa;border-radius:18px;">'
        '<tr><td style="padding:14px 18px;color:#9a3412;font-size:14px;line-height:1.6;font-weight:600;">'
        f"{html.escape(notice)}"
        "</td></tr></table></td></tr>"
    )


def _render_reference_block(references: list[str]) -> str:
    if not references:
        return ""

    items = []
    for reference in references:
        if " — " in reference:
            label, url = reference.split(" — ", 1)
        else:
            label, url = reference, reference
        safe_label = html.escape(label.strip() or url.strip())
        raw_url = url.strip()
        parsed = urlparse(raw_url)
        is_safe_link = parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
        safe_url = html.escape(raw_url)
        if is_safe_link:
            items.append(
                '<li style="margin:0 0 10px 0;padding:0;list-style:none;">'
                f'<a href="{safe_url}" style="color:#1d4ed8;text-decoration:none;font-size:14px;line-height:1.7;">{safe_label}</a>'
                "</li>"
            )
            continue

        items.append(
            '<li style="margin:0 0 10px 0;padding:0;list-style:none;color:#334155;font-size:14px;line-height:1.7;">'
            f"{safe_label}"
            "</li>"
        )

    return (
        '<tr><td style="padding:4px 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:20px;box-shadow:0 16px 32px rgba(15,23,42,0.04);">'
        '<tr><td style="padding:18px 22px 16px 22px;">'
        '<div style="font-size:15px;line-height:1.4;font-weight:700;color:#0f172a;padding:0 0 12px 0;">주요 참고 출처</div>'
        '<ul style="margin:0;padding:0;">'
        f"{''.join(items)}"
        "</ul>"
        "</td></tr></table></td></tr>"
    )


def _render_footer_note_block(notes: list[str]) -> str:
    if not notes:
        return ""

    items = "".join(
        '<li style="margin:0 0 10px 0;padding:0;list-style:none;color:#334155;font-size:14px;line-height:1.7;">'
        f"{html.escape(note)}"
        "</li>"
        for note in notes
    )
    return (
        '<tr><td style="padding:4px 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#fffbeb;border:1px solid #fde68a;border-radius:20px;box-shadow:0 10px 24px rgba(15,23,42,0.03);">'
        '<tr><td style="padding:18px 22px 16px 22px;">'
        '<div style="font-size:15px;line-height:1.4;font-weight:700;color:#78350f;padding:0 0 12px 0;">데이터 처리 메모</div>'
        '<ul style="margin:0;padding:0;">'
        f"{items}"
        "</ul>"
        "</td></tr></table></td></tr>"
    )


def _render_masthead_block(display_date: str) -> str:
    return (
        '<tr><td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="hero-card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:20px;overflow:hidden;box-shadow:0 10px 24px rgba(15,23,42,0.03);">'
        "<tr>"
        '<td class="hero-wrap" style="padding:22px 24px 20px 24px;background:#ffffff;">'
        f'<div style="padding:0 0 8px 0;color:#64748b;font-size:13px;line-height:1.5;font-weight:600;">{html.escape(display_date)}</div>'
        '<div class="hero-title" style="font-size:28px;line-height:1.24;font-weight:800;letter-spacing:-0.03em;color:#0f172a;-webkit-text-fill-color:#0f172a;">'
        "미국 기술주 · 비트코인 시장 브리핑"
        "</div>"
        "</td>"
        "</tr>"
        "</table>"
        "</td></tr>"
    )


def _render_top_summary_block(summary_lines: list[str]) -> str:
    if not summary_lines:
        return ""

    items = "".join(
        '<li style="margin:0 0 10px 0;padding:0;list-style:none;color:#0f172a;font-size:15px;line-height:1.75;">'
        f"{_render_body_line(line)}"
        "</li>"
        for line in summary_lines
    )
    return (
        '<tr><td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:20px;box-shadow:0 10px 24px rgba(15,23,42,0.03);">'
        '<tr><td style="padding:20px 22px 16px 22px;">'
        '<div style="font-size:12px;line-height:1.2;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;padding:0 0 10px 0;">핵심 요약</div>'
        f'<ul style="margin:0;padding:0;">{items}</ul>'
        "</td></tr></table></td></tr>"
    )


def _render_snapshot_block(snapshot_rows: list[tuple[str, str]]) -> str:
    if not snapshot_rows:
        return ""

    rows = "".join(
        "<tr>"
        '<td style="padding:10px 0;border-top:1px solid #e2e8f0;width:34%;vertical-align:top;">'
        f'<div style="font-size:12px;line-height:1.4;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;">{html.escape(label)}</div>'
        "</td>"
        '<td style="padding:10px 0;border-top:1px solid #e2e8f0;vertical-align:top;">'
        f'<div style="font-size:14px;line-height:1.7;color:#0f172a;">{_render_body_line(value)}</div>'
        "</td>"
        "</tr>"
        for label, value in snapshot_rows
    )
    return (
        '<tr><td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:20px;box-shadow:0 10px 24px rgba(15,23,42,0.03);">'
        '<tr><td style="padding:18px 22px 16px 22px;">'
        '<div style="font-size:12px;line-height:1.2;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;padding:0 0 6px 0;">주요 지표</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{rows}"
        "</table>"
        "</td></tr></table></td></tr>"
    )


def _render_email_document(
    *,
    subject: str,
    preheader: str,
    masthead_block: str,
    summary_block: str,
    snapshot_block: str,
    notice_block: str,
    section_rows: list[str],
    footer_note_block: str,
    reference_block: str,
) -> str:
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title>{html.escape(subject)}</title>
    <style>
      body, table, td {{
        font-family: "Pretendard Variable", Pretendard, "SUIT Variable", SUIT, Roboto,
          "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "Segoe UI",
          "Helvetica Neue", Helvetica, Arial, sans-serif;
      }}
      @media screen and (max-width: 600px) {{
        .hero-wrap {{
          padding:20px 20px 18px 20px !important;
        }}
        .hero-title {{
          font-size:24px !important;
          line-height:1.22 !important;
        }}
      }}
    </style>
  </head>
  <body style="margin:0;padding:0;background:#f3f6fb;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      {html.escape(preheader)}
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="shell" style="background:#f3f6fb;">
      <tr>
        <td align="center" style="padding:28px 14px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:680px;">
            {masthead_block}
            {summary_block}
            {snapshot_block}
            {notice_block}
            {"".join(section_rows)}
            {footer_note_block}
            {reference_block}
            <tr>
              <td style="padding:8px 6px 0 6px;color:#64748b;font-size:12px;line-height:1.7;text-align:center;">
                본 자료는 공개 시장 데이터와 신뢰 가능한 외부 출처를 바탕으로 작성한 일반 정보성 브리핑입니다. 특정 자산에 대한 투자 권유나 자문에 해당하지 않으며, 시장 상황에 따라 수치와 해석은 달라질 수 있습니다.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


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
