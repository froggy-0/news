from __future__ import annotations

import base64
from email import message_from_bytes

from morning_brief.config import load_settings
from morning_brief.emailer import GmailSender, _unsubscribe_url, build_briefing_message
from morning_brief.subscriptions.models import ActiveRecipient


def _configure_mail_settings(monkeypatch):
    monkeypatch.setenv("GMAIL_SENDER", "brief@example.com")
    monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://brief.example.com")
    monkeypatch.setenv("SUBSCRIPTION_UNSUBSCRIBE_PATH", "/unsubscribe")
    monkeypatch.setenv("SUBSCRIPTION_NEWSLETTER_KEY", "morning-brief")
    monkeypatch.setenv("SUBSCRIPTION_TOKEN_SECRET", "token-secret")
    return load_settings()


def test_unsubscribe_url_uses_public_url_and_signed_token(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    recipient = ActiveRecipient(
        email="reader@example.com",
        subscriber_id="sub_123",
        newsletter="morning-brief",
    )

    unsubscribe_url = _unsubscribe_url(settings=settings, recipient=recipient, sender="")

    assert unsubscribe_url.startswith("https://brief.example.com/unsubscribe?token=")
    assert "reader%40example.com" not in unsubscribe_url


def test_build_briefing_message_renders_recipient_specific_unsubscribe_url(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    recipient = ActiveRecipient(
        email="reader@example.com",
        subscriber_id="sub_123",
        newsletter="morning-brief",
    )
    unsubscribe_url = _unsubscribe_url(settings=settings, recipient=recipient, sender="")

    msg = build_briefing_message(
        subject="테스트 브리핑",
        body="## Section 0\n\n시장 점검\n",
        sender=settings.gmail_sender,
        recipient=recipient.email,
        unsubscribe_url=unsubscribe_url,
        packet={"date": "2026-03-28"},
    )

    text_part = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")
    html_part = msg.get_payload()[1].get_payload(decode=True).decode("utf-8")

    assert msg["to"] == "reader@example.com"
    assert msg["List-Unsubscribe"] == f"<{unsubscribe_url}>"
    assert "bcc" not in {key.lower() for key in msg.keys()}
    assert unsubscribe_url in text_part
    assert unsubscribe_url in html_part


def test_gmail_sender_sends_each_active_recipient_individually(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    sender = GmailSender(settings)
    recipients = [
        ActiveRecipient(
            email="reader1@example.com",
            subscriber_id="sub_1",
            newsletter="morning-brief",
        ),
        ActiveRecipient(
            email="reader2@example.com",
            subscriber_id="sub_2",
            newsletter="morning-brief",
        ),
    ]

    class FakeRepository:
        def list_active_recipients(self, newsletter: str):
            assert newsletter == "morning-brief"
            return recipients

    sent_raw_messages: list[str] = []

    class _FakeSendRequest:
        def __init__(self, body):
            self._body = body

        def execute(self):
            sent_raw_messages.append(self._body["raw"])
            return {"id": "msg_123"}

    class _FakeMessagesResource:
        def send(self, *, userId, body):
            assert userId == "me"
            return _FakeSendRequest(body)

    class _FakeUsersResource:
        def messages(self):
            return _FakeMessagesResource()

    class _FakeService:
        def users(self):
            return _FakeUsersResource()

    monkeypatch.setattr(sender, "_subscription_repository", lambda: FakeRepository())
    monkeypatch.setattr(sender, "_load_credentials", lambda: object())
    monkeypatch.setattr(
        "morning_brief.emailer._gmail_dependencies",
        lambda: (object(), object(), object(), lambda *args, **kwargs: _FakeService()),
    )

    sender.send(subject="테스트 브리핑", body="## Section 0\n\n시장 점검\n", packet={"date": "2026-03-28"})

    assert len(sent_raw_messages) == 2

    decoded_messages = [
        message_from_bytes(base64.urlsafe_b64decode(raw.encode("utf-8"))) for raw in sent_raw_messages
    ]

    assert decoded_messages[0]["to"] == "reader1@example.com"
    assert decoded_messages[1]["to"] == "reader2@example.com"
    assert decoded_messages[0]["List-Unsubscribe"] != decoded_messages[1]["List-Unsubscribe"]


def test_gmail_sender_skips_when_no_active_recipients(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    sender = GmailSender(settings)

    class FakeRepository:
        def list_active_recipients(self, newsletter: str):
            assert newsletter == "morning-brief"
            return []

    def _unexpected_credentials_load():
        raise AssertionError("credentials should not be loaded when there are no active recipients")

    monkeypatch.setattr(sender, "_subscription_repository", lambda: FakeRepository())
    monkeypatch.setattr(sender, "_load_credentials", _unexpected_credentials_load)

    sender.send(subject="테스트 브리핑", body="## Section 0\n\n시장 점검\n", packet={"date": "2026-03-28"})
