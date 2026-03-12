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


def _text_to_html_blocks(content: str) -> str:
    blocks: list[str] = []
    paragraphs = [chunk.strip() for chunk in content.split("\n\n") if chunk.strip()]

    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if lines and all(line.startswith("- ") for line in lines):
            items = "".join(
                f'<li style="margin:0 0 10px 0;padding-left:0;">{html.escape(line[2:].strip())}</li>'
                for line in lines
            )
            blocks.append(
                '<ul style="margin:0;padding:0;list-style-position:inside;color:#1f2937;font-size:15px;'
                'line-height:1.75;">'
                f"{items}</ul>"
            )
            continue

        text = "<br>".join(html.escape(line) for line in lines)
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


def render_briefing_email_html(subject: str, body: str) -> str:
    title, notice, sections = _extract_brief_structure(body)
    preheader = _preheader_text(title=title, notice=notice, sections=sections)
    generated_label = subject.split("|")[-1].strip() or title

    section_rows = []
    for index, (heading, content) in enumerate(sections, start=1):
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
        section_rows.append(
            f"""
            <tr>
              <td style="padding:0 0 16px 0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" style="border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #dbe4ee;border-radius:24px;">
                  <tr>
                    <td style="padding:22px 24px 22px 24px;">
                      <div style="width:36px;height:36px;line-height:36px;text-align:center;background:#0f172a;color:#ffffff;border-radius:999px;font-size:14px;font-weight:700;">{index}</div>
                      <div style="font-size:20px;line-height:1.3;font-weight:700;color:#0f172a;padding:14px 0 12px 0;">{html.escape(heading)}</div>
                      {summary_block}
                      {insight_block}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """.strip()
        )

    notice_block = ""
    if notice:
        notice_block = (
            '<tr><td style="padding:0 0 16px 0;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border-collapse:separate;border-spacing:0;background:#fff7ed;border:1px solid #fed7aa;border-radius:18px;">'
            '<tr><td style="padding:14px 18px;color:#9a3412;font-size:14px;line-height:1.6;font-weight:600;">'
            f"{html.escape(notice)}"
            "</td></tr></table></td></tr>"
        )

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
      .hero-kicker {{
        font-size:12px;
        line-height:1.2;
        letter-spacing:0.12em;
        text-transform:uppercase;
        color:#dbeafe;
        font-weight:700;
      }}
      .hero-title {{
        font-size:36px;
        line-height:1.14;
        letter-spacing:-0.03em;
        font-weight:800;
        color:#f8fafc;
      }}
      .hero-copy {{
        font-size:15px;
        line-height:1.78;
        color:#dbeafe;
      }}
      .hero-meta {{
        font-size:13px;
        line-height:1.6;
        color:#dbeafe;
        opacity:0.92;
      }}
      @media screen and (max-width: 600px) {{
        .hero-wrap {{
          padding:24px 22px 22px 22px !important;
        }}
        .hero-title {{
          font-size:30px !important;
          line-height:1.18 !important;
        }}
        .hero-copy {{
          font-size:14px !important;
          line-height:1.75 !important;
        }}
      }}
      @media (prefers-color-scheme: dark) {{
        body {{
          background:#07111f !important;
        }}
        .shell {{
          background:#07111f !important;
        }}
        .card {{
          background:#0f172a !important;
          border-color:#243145 !important;
        }}
        .ink {{
          color:#e5eef8 !important;
        }}
        .muted {{
          color:#9fb0c7 !important;
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
            <tr>
              <td style="padding:0 0 16px 0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="card" style="border-collapse:separate;border-spacing:0;background:#0f172a;border-radius:28px;overflow:hidden;">
                  <tr>
                    <td class="hero-wrap" style="padding:28px 28px 24px 28px;background:#0f172a;background-image:linear-gradient(135deg,#0f172a 0%,#1d4ed8 140%);">
                      <div class="hero-kicker" style="padding:0 0 14px 0;">좋은 아침 시장 브리핑</div>
                      <div class="hero-copy" style="padding:0 0 14px 0;">
                        <div>안녕하세요.</div>
                        <div>오늘 아침 시장 흐름을 편하게 읽으실 수 있도록 정리했어요.</div>
                      </div>
                      <div class="hero-title" style="padding:0 0 14px 0;">
                        오늘의 미국 기술주와 비트코인 흐름을<br>
                        한 번에 읽으실 수 있게 담았어요.
                      </div>
                      <div class="hero-copy" style="max-width:520px;">
                        <div>핵심 수치를 먼저 짚어드렸어요.</div>
                        <div>바로 아래에서 흐름과 의미를 자연스럽게 읽으실 수 있어요.</div>
                      </div>
                      <div class="hero-meta" style="padding-top:18px;">
                        {html.escape(generated_label)}
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            {notice_block}
            {''.join(section_rows)}
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
