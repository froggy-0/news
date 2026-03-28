from __future__ import annotations

from morning_brief.subscriptions.models import ActiveRecipient
from morning_brief.subscriptions.supabase_repository import SupabaseSubscriptionRepository


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, _fields: str):
        return self

    def eq(self, _field: str, _value: str):
        return self

    def execute(self):
        class _Response:
            def __init__(self, data):
                self.data = data

        return _Response(self._data)


class _FakeClient:
    def __init__(self, data):
        self._data = data

    def table(self, _table_name: str):
        return _FakeQuery(self._data)


def test_list_active_recipients_returns_mapped_records(monkeypatch):
    fake_data = [
        {
            "id": "sub_1",
            "email": "one@example.com",
            "newsletter": "morning-brief",
            "status": "active",
        },
        {
            "id": "sub_2",
            "email": "two@example.com",
            "newsletter": "morning-brief",
            "status": "active",
        },
    ]

    monkeypatch.setattr(
        "morning_brief.subscriptions.supabase_repository.create_client",
        lambda _url, _key: _FakeClient(fake_data),
    )

    repository = SupabaseSubscriptionRepository(
        supabase_url="https://example.supabase.co",
        service_role_key="service-role-key",
    )

    assert repository.list_active_recipients("morning-brief") == [
        ActiveRecipient(email="one@example.com", subscriber_id="sub_1", newsletter="morning-brief"),
        ActiveRecipient(email="two@example.com", subscriber_id="sub_2", newsletter="morning-brief"),
    ]


def test_repository_requires_supabase_settings():
    try:
        SupabaseSubscriptionRepository(supabase_url="", service_role_key="")
    except ValueError as exc:
        assert "SUPABASE_URL" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Expected ValueError for missing Supabase settings")
