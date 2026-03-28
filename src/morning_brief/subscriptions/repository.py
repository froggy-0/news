from __future__ import annotations

from typing import Protocol

from morning_brief.subscriptions.models import ActiveRecipient


class SubscriptionRepository(Protocol):
    def list_active_recipients(self, newsletter: str) -> list[ActiveRecipient]: ...
