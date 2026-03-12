from __future__ import annotations

import base64
from email.mime.text import MIMEText
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from morning_brief.config import Settings

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

logger = logging.getLogger(__name__)


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

        if not self.settings.gmail_sender or not self.settings.gmail_recipient:
            raise ValueError("GMAIL_SENDER and GMAIL_RECIPIENT are required when SEND_EMAIL=true")

        creds = self._load_credentials()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        msg = MIMEText(body, _subtype="plain", _charset="utf-8")
        msg["to"] = self.settings.gmail_recipient
        msg["from"] = self.settings.gmail_sender
        msg["subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        logger.info("Briefing email sent to %s", self.settings.gmail_recipient)
