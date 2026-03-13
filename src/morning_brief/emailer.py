from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from morning_brief.brief_formatting import (
    extract_brief_structure as _extract_brief_structure,
    split_reference_block as _split_reference_block,
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

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials
else:  # pragma: no cover - runtime import guard
    Credentials = Any


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


def _build_top_summary_lines(sections: list[tuple[str, str]]) -> list[str]:
    lines: list[str] = []
    for heading, content in sections:
        groups = _split_section_groups(content)
        conclusion = groups["conclusion"][1]
        insight = groups["insight"][1]
        candidate = _first_non_empty_paragraph(conclusion) or _first_non_empty_paragraph(insight)
        if candidate:
            if candidate.startswith("- "):
                candidate = candidate[2:].strip()
            lines.append(candidate)
        if len(lines) >= 3:
            break
    return lines


def _build_snapshot_rows(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for heading, content in sections[:4]:
        groups = _split_section_groups(content)
        metric_line = _first_metric_line(groups["metrics"][1])
        if metric_line:
            rows.append((heading, metric_line))
    return rows


def _direction_color(direction: str) -> str:
    if direction == "up":
        return "#dc2626"
    if direction == "down":
        return "#2563eb"
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
            token_direction = default_direction if default_direction in {"up", "down", "flat"} else "neutral"
        color = _direction_color(token_direction)
        parts.append(html.escape(text[last_index:start]))
        parts.append(f'<span style="color:{color};font-weight:700;">{html.escape(token)}</span>')
        last_index = end

    if not parts:
        return html.escape(text)

    parts.append(html.escape(text[last_index:]))
    return "".join(parts)


def _render_body_line(text: str) -> str:
    highlighted = _highlight_metric_text(text, default_direction=_token_direction(text) or "neutral")
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
            items = "".join(
                _render_metric_item(line[2:].strip())
                for line in lines
            )
            blocks.append(
                '<ul style="margin:0;padding:0;list-style:none;color:#1f2937;font-size:15px;'
                'line-height:1.75;">'
                f"{items}</ul>"
            )
            continue

        text = "<br>".join(_render_body_line(line) for line in lines)
        blocks.append(
            '<p style="margin:0;color:#1f2937;font-size:15px;line-height:1.8;">'
            f"{text}</p>"
        )

    return "".join(blocks) or (
        '<p style="margin:0;color:#1f2937;font-size:15px;line-height:1.8;">'
        "내용이 없습니다.</p>"
    )


def _preheader_text(title: str, notice: str, sections: list[tuple[str, str]]) -> str:
    if notice:
        return notice[:140]
    summary_lines = _build_top_summary_lines(sections)
    if summary_lines:
        return " | ".join(summary_lines)[:140]
    if sections:
        return f"{title} | {sections[0][1][:120]}".strip()
    return title


def _render_section_row(index: int, heading: str, content: str) -> str:
    groups = _split_section_groups(content)
    conclusion_label, conclusion_content = groups["conclusion"]
    metrics_label, metrics_content = groups["metrics"]
    insight_label, insight_content = groups["insight"]
    watch_label, watch_content = groups["watch"]
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
        '<tr>'
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
            {''.join(section_rows)}
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


def render_briefing_email_html(subject: str, body: str) -> str:
    main_body, references = _split_reference_block(body)
    title, notice, sections = _extract_brief_structure(main_body)
    display_date = _format_display_date(title=title, subject=subject)
    summary_lines = _build_top_summary_lines(sections)
    snapshot_rows = _build_snapshot_rows(sections)
    preheader = _preheader_text(title=title, notice=notice, sections=sections)
    section_rows = [
        _render_section_row(index=index, heading=heading, content=content)
        for index, (heading, content) in enumerate(sections, start=1)
    ]
    return _render_email_document(
        subject=subject,
        preheader=preheader,
        masthead_block=_render_masthead_block(display_date=display_date),
        summary_block=_render_top_summary_block(summary_lines),
        snapshot_block=_render_snapshot_block(snapshot_rows),
        notice_block=_render_notice_block(notice),
        section_rows=section_rows,
        reference_block=_render_reference_block(references),
    )


def build_briefing_message(
    *,
    subject: str,
    body: str,
    sender: str,
    recipients: list[str],
) -> MIMEMultipart:
    html_body = render_briefing_email_html(subject=subject, body=body)
    msg = MIMEMultipart("alternative")
    msg["to"] = recipients[0] if len(recipients) == 1 else sender
    if len(recipients) > 1:
        msg["bcc"] = ", ".join(recipients)
    msg["from"] = sender
    msg["subject"] = subject
    msg.attach(MIMEText(body, _subtype="plain", _charset="utf-8"))
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
