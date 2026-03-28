from __future__ import annotations

from supabase import Client, create_client

from morning_brief.subscriptions.models import ActiveRecipient


class SupabaseSubscriptionRepository:
    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        table_name: str = "subscriptions",
    ) -> None:
        if not supabase_url or not service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self._table_name = table_name
        self._client: Client = create_client(supabase_url, service_role_key)

    def list_active_recipients(self, newsletter: str) -> list[ActiveRecipient]:
        response = (
            self._client.table(self._table_name)
            .select("id,email,newsletter,status")
            .eq("newsletter", newsletter)
            .eq("status", "active")
            .execute()
        )
        data = response.data
        if not isinstance(data, list):
            return []

        recipients: list[ActiveRecipient] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email", "")).strip()
            subscriber_id = str(item.get("id", "")).strip()
            item_newsletter = str(item.get("newsletter", "")).strip() or newsletter
            if not email or not subscriber_id:
                continue
            recipients.append(
                ActiveRecipient(
                    email=email,
                    subscriber_id=subscriber_id,
                    newsletter=item_newsletter,
                )
            )
        return recipients
