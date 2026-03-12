from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import logging
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from morning_brief.config import Settings

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

logger = logging.getLogger(__name__)
SECTION_HEADING_RE = re.compile(r"^(\d+)\.\s+(.+)$")
SUMMARY_LABELS = {"수치 체크", "핵심 내용", "오늘 볼 포인트", "체크 포인트"}
INSIGHT_LABELS = {"해석", "이렇게 읽으면 돼요"}
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“”‘’(]*[A-Za-z가-힣])")
PERCENT_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%")
UP_TOKENS = ("올랐", "상승", "강세", "반등", "높아졌", "증가", "확대", "유입", "개선", "회복")
DOWN_TOKENS = ("내렸", "하락", "약세", "밀렸", "낮아졌", "감소", "축소", "유출", "둔화", "후퇴")
FLAT_TOKENS = ("보합", "유지", "비슷", "변동이 크지", "큰 변화는 없")


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


def _extract_brief_structure(body: str) -> tuple[str, str, list[tuple[str, str]]]:
    lines = [line.rstrip() for line in body.replace("\r\n", "\n").split("\n")]
    title = lines[0].strip() if lines else "Morning Market Brief"

    notice = ""
    start_index = 1
    if len(lines) > 1 and lines[1].strip().startswith("[데이터 품질 알림]"):
        notice = lines[1].strip()
        start_index = 2

    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush_section() -> None:
        nonlocal current_heading, current_lines
        if not current_heading:
            return
        content = "\n".join(current_lines).strip()
        sections.append((current_heading, content))
        current_heading = ""
        current_lines = []

    for raw_line in lines[start_index:]:
        line = raw_line.strip()
        if not line and not current_heading:
            continue

        match = SECTION_HEADING_RE.match(line)
        if match:
            flush_section()
            current_heading = match.group(2).strip()
            continue

        if current_heading:
            current_lines.append(raw_line.strip())

    flush_section()
    return title, notice, sections


def _split_reference_block(body: str) -> tuple[str, list[str]]:
    marker = "\n참고 출처\n"
    if marker not in body:
        return body, []

    main_body, raw_references = body.split(marker, 1)
    references = [line.strip()[2:].strip() for line in raw_references.splitlines() if line.strip().startswith("- ")]
    return main_body.strip(), references


def _expand_sentence_spacing(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("- "):
            lines.append(stripped)
            continue
        expanded = SENTENCE_BREAK_RE.sub("\n\n", stripped)
        lines.extend(part.strip() for part in expanded.splitlines())
    return "\n".join(lines).strip()


def _split_section_groups(content: str) -> tuple[str, str, str]:
    normalized = _expand_sentence_spacing(content)
    current_kind = "summary"
    current_label = "핵심 요약"
    sections = {
        "summary": {"label": "핵심 요약", "lines": []},
        "insight": {"label": "이렇게 읽으면 좋아요", "lines": []},
    }
    explicit_labels_found = False

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            sections[current_kind]["lines"].append("")
            continue

        if line in SUMMARY_LABELS:
            current_kind = "summary"
            current_label = line
            sections["summary"]["label"] = current_label
            explicit_labels_found = True
            continue

        if line in INSIGHT_LABELS:
            current_kind = "insight"
            current_label = line
            sections["insight"]["label"] = current_label
            explicit_labels_found = True
            continue

        sections[current_kind]["lines"].append(line)

    if not explicit_labels_found:
        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        if paragraphs:
            sections["summary"]["lines"] = [paragraphs[0]]
            sections["insight"]["lines"] = paragraphs[1:]

    summary = "\n".join(sections["summary"]["lines"]).strip()
    insight = "\n".join(sections["insight"]["lines"]).strip()
    return sections["summary"]["label"], summary, insight


def _direction_style(direction: str) -> tuple[str, str, str, str]:
    if direction == "up":
        return "↑", "#dc2626", "#fef2f2", "#fecaca"
    if direction == "down":
        return "↓", "#2563eb", "#eff6ff", "#bfdbfe"
    if direction == "mixed":
        return "↕", "#64748b", "#f8fafc", "#cbd5e1"
    if direction == "flat":
        return "→", "#64748b", "#f8fafc", "#cbd5e1"
    return "•", "#94a3b8", "#f8fafc", "#e2e8f0"


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


def _metric_indicator(text: str) -> tuple[str, str, str, str]:
    signed_directions = [
        direction
        for token in PERCENT_RE.findall(text)
        if (direction := _percent_direction(token)) is not None
    ]
    positive_count = sum(1 for direction in signed_directions if direction == "up")
    negative_count = sum(1 for direction in signed_directions if direction == "down")

    if positive_count and negative_count:
        return _direction_style("mixed")
    if positive_count:
        return _direction_style("up")
    if negative_count:
        return _direction_style("down")
    if signed_directions and all(direction == "flat" for direction in signed_directions):
        return _direction_style("flat")

    token_direction = _token_direction(text)
    if token_direction is not None:
        return _direction_style(token_direction)

    if signed_directions:
        return _direction_style("flat")

    return _direction_style("neutral")


def _highlight_metric_text(text: str, default_direction: str) -> str:
    parts: list[str] = []
    last_index = 0

    for match in PERCENT_RE.finditer(text):
        start, end = match.span()
        token = match.group(0)
        token_direction = _percent_direction(token)
        if token_direction is None:
            token_direction = default_direction if default_direction in {"up", "down", "flat"} else "neutral"
        _, color, _, _ = _direction_style(token_direction)
        parts.append(html.escape(text[last_index:start]))
        parts.append(f'<span style="color:{color};font-weight:700;">{html.escape(token)}</span>')
        last_index = end

    if not parts:
        return html.escape(text)

    parts.append(html.escape(text[last_index:]))
    return "".join(parts)


def _render_body_line(text: str) -> str:
    symbol, color, background, border = _metric_indicator(text)
    highlighted = _highlight_metric_text(text, default_direction=_token_direction(text) or "neutral")
    if symbol == "•" and highlighted == html.escape(text):
        return html.escape(text)
    return (
        f'<span style="display:inline-block;min-width:18px;height:18px;line-height:18px;'
        f'text-align:center;border-radius:999px;background:{background};border:1px solid {border};'
        f'color:{color};font-weight:800;font-size:11px;vertical-align:1px;margin-right:8px;">{symbol}</span>'
        f'<span style="display:inline;color:#0f172a;">{highlighted}</span>'
    )


def _render_metric_item(text: str) -> str:
    symbol, color, background, border = _metric_indicator(text)
    default_direction = _token_direction(text) or "neutral"
    return (
        '<li style="margin:0 0 10px 0;padding:0;list-style:none;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;">'
        "<tr>"
        '<td valign="top" style="padding:0 10px 0 0;">'
        f'<span style="display:inline-block;min-width:22px;height:22px;line-height:22px;'
        f'text-align:center;border-radius:999px;background:{background};border:1px solid {border};'
        f'color:{color};font-weight:800;font-size:13px;">{symbol}</span>'
        "</td>"
        '<td valign="top" style="padding:0;">'
        f'<span style="display:inline;color:#0f172a;font-size:15px;line-height:1.75;">{_highlight_metric_text(text, default_direction)}</span>'
        "</td>"
        "</tr>"
        "</table>"
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
    if sections:
        return f"{title} | {sections[0][1][:120]}".strip()
    return title


def _render_section_row(index: int, heading: str, content: str) -> str:
    summary_label, summary_content, insight_content = _split_section_groups(content)
    summary_block = ""
    if summary_content:
        summary_block = (
            '<div style="padding:0 0 14px 0;">'
            f'<div style="font-size:12px;line-height:1.2;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#2563eb;padding:0 0 10px 0;">{html.escape(summary_label)}</div>'
            f"{_text_to_html_blocks(summary_content)}"
            "</div>"
        )
    insight_block = ""
    if insight_content:
        insight_block = (
            '<div style="padding:0;">'
            '<div style="font-size:12px;line-height:1.2;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#0f172a;padding:0 0 10px 0;">해석</div>'
            f"{_text_to_html_blocks(insight_content)}"
            "</div>"
        )
    return (
        "<tr>"
        '<td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:24px;">'
        "<tr>"
        '<td style="padding:22px 24px 22px 24px;">'
        f'<div style="width:36px;height:36px;line-height:36px;text-align:center;background:#0f172a;color:#ffffff;border-radius:999px;font-size:14px;font-weight:700;">{index}</div>'
        f'<div style="font-size:20px;line-height:1.3;font-weight:700;color:#0f172a;padding:14px 0 12px 0;">{html.escape(heading)}</div>'
        f"{summary_block}"
        f"{insight_block}"
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
        safe_url = html.escape(url.strip())
        items.append(
            '<li style="margin:0 0 10px 0;padding:0;list-style:none;">'
            f'<a href="{safe_url}" style="color:#1d4ed8;text-decoration:none;font-size:14px;line-height:1.7;">{safe_label}</a>'
            "</li>"
        )

    return (
        '<tr><td style="padding:4px 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" '
        'style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:20px;">'
        '<tr><td style="padding:18px 22px 16px 22px;">'
        '<div style="font-size:15px;line-height:1.4;font-weight:700;color:#0f172a;padding:0 0 12px 0;">참고 출처</div>'
        '<ul style="margin:0;padding:0;">'
        f"{''.join(items)}"
        "</ul>"
        "</td></tr></table></td></tr>"
    )


def _render_hero_block(generated_label: str) -> str:
    return (
        '<tr><td style="padding:0 0 16px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="hero-card" '
        'style="border-collapse:separate;border-spacing:0;background:#f8fbff;border:1px solid #dbe4ee;border-radius:28px;overflow:hidden;">'
        "<tr>"
        '<td class="hero-wrap" style="padding:28px 28px 24px 28px;background:#ffffff;">'
        '<div style="padding:0 0 16px 0;">'
        '<span style="display:inline-block;padding:7px 12px;border-radius:999px;border:1px solid #dbe4ee;background:#f8fafc;color:#0f172a;font-size:12px;line-height:1.2;font-weight:700;letter-spacing:0.02em;-webkit-text-fill-color:#0f172a;">좋은 아침 시장 브리핑</span>'
        "</div>"
        '<div class="hero-copy" style="padding:0 0 14px 0;font-size:15px;line-height:1.8;color:#334155;-webkit-text-fill-color:#334155;">'
        "<div>안녕하세요.</div>"
        "<div>오늘 아침에 꼭 봐야 할 시장 흐름만 편하게 읽으실 수 있게 정리했어요.</div>"
        "</div>"
        '<div class="hero-title" style="padding:0 0 14px 0;font-size:34px;line-height:1.2;font-weight:800;letter-spacing:-0.03em;color:#0f172a;-webkit-text-fill-color:#0f172a;">'
        "오늘 아침,<br>"
        '<span style="color:#1d4ed8;-webkit-text-fill-color:#1d4ed8;">미국 기술주와 비트코인</span> 흐름만<br>'
        "편하게 읽으실 수 있게 담았어요."
        "</div>"
        '<div class="hero-copy" style="max-width:540px;font-size:15px;line-height:1.8;color:#475569;-webkit-text-fill-color:#475569;">'
        '<div><span style="color:#0f172a;font-weight:700;-webkit-text-fill-color:#0f172a;">수치 체크</span>만 먼저 읽으셔도 흐름이 바로 잡히도록 구성했어요.</div>'
        '<div>조금 더 여유가 있으실 때는 아래 <span style="color:#0f172a;font-weight:700;-webkit-text-fill-color:#0f172a;">해석</span>까지 보시면 의미가 더 쉽게 연결되실 거예요.</div>'
        "</div>"
        '<div class="hero-copy" style="padding-top:18px;font-size:13px;line-height:1.6;color:#64748b;-webkit-text-fill-color:#64748b;">'
        f"{html.escape(generated_label)}"
        "</div>"
        "</td>"
        "</tr>"
        "</table>"
        "</td></tr>"
    )


def _render_email_document(
    *,
    subject: str,
    preheader: str,
    hero_block: str,
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
          padding:24px 22px 22px 22px !important;
        }}
        .hero-title {{
          font-size:29px !important;
          line-height:1.22 !important;
        }}
        .hero-copy {{
          font-size:14px !important;
          line-height:1.75 !important;
        }}
      }}
    </style>
  </head>
  <body style="margin:0;padding:0;background:#edf2f7;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      {html.escape(preheader)}
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="shell" style="background:#edf2f7;">
      <tr>
        <td align="center" style="padding:28px 14px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:680px;">
            {hero_block}
            {notice_block}
            {''.join(section_rows)}
            {reference_block}
            <tr>
              <td style="padding:8px 6px 0 6px;color:#64748b;font-size:12px;line-height:1.7;text-align:center;">
                자동으로 정리된 시장 브리핑 메일이에요. 투자 권유가 아닌 정보 전달 목적의 요약입니다.
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
    preheader = _preheader_text(title=title, notice=notice, sections=sections)
    generated_label = subject.split("|")[-1].strip() or title
    section_rows = [
        _render_section_row(index=index, heading=heading, content=content)
        for index, (heading, content) in enumerate(sections, start=1)
    ]
    return _render_email_document(
        subject=subject,
        preheader=preheader,
        hero_block=_render_hero_block(generated_label),
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
        creds: Credentials | None = None
        if self.settings.gmail_token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.settings.gmail_token_file), SCOPES
                )
            except Exception as exc:
                logger.warning("Failed to parse token file. Re-auth required: %s", exc)

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
            logger.info("SEND_EMAIL=false. Skipping Gmail send.")
            return

        recipients = _split_recipients(self.settings.gmail_recipient)
        if not self.settings.gmail_sender or not recipients:
            raise ValueError("GMAIL_SENDER and GMAIL_RECIPIENT are required when SEND_EMAIL=true")

        creds = self._load_credentials()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        msg = build_briefing_message(
            subject=subject,
            body=body,
            sender=self.settings.gmail_sender,
            recipients=recipients,
        )

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        logger.info("Briefing email sent to %s recipient(s)", len(recipients))
