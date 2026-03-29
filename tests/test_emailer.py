from __future__ import annotations

from email import message_from_bytes

from morning_brief.config import load_settings
from morning_brief.emailer import SesSender, _unsubscribe_url, build_briefing_message
from morning_brief.subscriptions.models import ActiveRecipient


def _configure_mail_settings(monkeypatch):
    monkeypatch.setenv("SES_SENDER", "no-reply@sovereignbriefing.com")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://brief.example.com")
    monkeypatch.setenv("SUBSCRIPTION_TOKEN_SECRET", "token-secret")
    return load_settings()


def test_unsubscribe_url_uses_public_url_and_signed_token(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    recipient = ActiveRecipient(
        email="reader@example.com",
        subscriber_id="sub_123",
        newsletter="morning-brief",
    )

    unsubscribe_url = _unsubscribe_url(settings=settings, recipient=recipient)

    assert unsubscribe_url.startswith("https://brief.example.com/unsubscribe?token=")
    assert "reader%40example.com" not in unsubscribe_url


def test_build_briefing_message_renders_recipient_specific_unsubscribe_url(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    recipient = ActiveRecipient(
        email="reader@example.com",
        subscriber_id="sub_123",
        newsletter="morning-brief",
    )
    unsubscribe_url = _unsubscribe_url(settings=settings, recipient=recipient)

    msg = build_briefing_message(
        subject="테스트 브리핑",
        body="## Section 0\n\n시장 점검\n",
        sender=settings.ses_sender,
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


def test_ses_sender_sends_each_active_recipient_individually(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    sender = SesSender(settings)
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

    sent_raw_messages: list[bytes] = []
    sent_sources: list[str] = []
    sent_destinations: list[list[str]] = []

    class _FakeService:
        def send_raw_email(self, **kwargs):
            sent_sources.append(kwargs["Source"])
            sent_destinations.append(kwargs["Destinations"])
            sent_raw_messages.append(kwargs["RawMessage"]["Data"])
            return {"MessageId": "msg_123"}

    monkeypatch.setattr(sender, "_subscription_repository", lambda: FakeRepository())
    monkeypatch.setattr(sender, "_ses_client", lambda: _FakeService())

    sender.send(
        subject="테스트 브리핑", body="## Section 0\n\n시장 점검\n", packet={"date": "2026-03-28"}
    )

    assert len(sent_raw_messages) == 2
    assert sent_sources == ["no-reply@sovereignbriefing.com", "no-reply@sovereignbriefing.com"]
    assert sent_destinations == [["reader1@example.com"], ["reader2@example.com"]]

    decoded_messages = [message_from_bytes(raw) for raw in sent_raw_messages]

    assert decoded_messages[0]["to"] == "reader1@example.com"
    assert decoded_messages[1]["to"] == "reader2@example.com"
    assert decoded_messages[0]["from"] == "no-reply@sovereignbriefing.com"
    assert decoded_messages[0]["List-Unsubscribe"] != decoded_messages[1]["List-Unsubscribe"]


def test_ses_sender_skips_when_no_active_recipients(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    sender = SesSender(settings)

    class FakeRepository:
        def list_active_recipients(self, newsletter: str):
            assert newsletter == "morning-brief"
            return []

    def _unexpected_client_load():
        raise AssertionError("SES client should not be loaded when there are no active recipients")

    monkeypatch.setattr(sender, "_subscription_repository", lambda: FakeRepository())
    monkeypatch.setattr(sender, "_ses_client", _unexpected_client_load)

    sender.send(
        subject="테스트 브리핑", body="## Section 0\n\n시장 점검\n", packet={"date": "2026-03-28"}
    )


def test_ses_sender_logs_identity_failure_context(monkeypatch):
    settings = _configure_mail_settings(monkeypatch)
    sender = SesSender(settings)
    recipient = ActiveRecipient(
        email="reader@example.com",
        subscriber_id="sub_123",
        newsletter="morning-brief",
    )

    class FakeRepository:
        def list_active_recipients(self, newsletter: str):
            assert newsletter == "morning-brief"
            return [recipient]

    class FakeClientError(Exception):
        def __init__(self) -> None:
            super().__init__("Email address is not verified.")
            self.response = {
                "Error": {
                    "Code": "MessageRejected",
                    "Message": "Email address is not verified.",
                }
            }

    class _FailingService:
        def send_raw_email(self, **kwargs):
            raise FakeClientError()

    events: list[dict[str, object]] = []

    def _capture_log(*args, **kwargs):
        events.append(kwargs)

    monkeypatch.setattr(sender, "_subscription_repository", lambda: FakeRepository())
    monkeypatch.setattr(sender, "_ses_client", lambda: _FailingService())
    monkeypatch.setattr("morning_brief.emailer.log_structured", _capture_log)

    try:
        sender.send(
            subject="테스트 브리핑",
            body="## Section 0\n\n시장 점검\n",
            packet={"date": "2026-03-28"},
        )
    except RuntimeError as exc:
        assert "Failed to send newsletter to 1 recipients" in str(exc)
    else:
        raise AssertionError("expected SES send failure to raise RuntimeError")

    error_event = next(item for item in events if item.get("event") == "error.raised")
    assert error_event["failure_category"] == "identity_failure"
    assert error_event["aws_error_code"] == "MessageRejected"
    assert error_event["reason"] == "Email address is not verified."
