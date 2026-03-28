from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SubscriptionStatus = Literal["pending", "active", "unsubscribed", "bounced"]


@dataclass(frozen=True)
class ActiveRecipient:
    email: str
    subscriber_id: str
    newsletter: str


@dataclass(frozen=True)
class SubscriptionRecord:
    subscriber_id: str
    email: str
    email_normalized: str
    newsletter: str
    status: SubscriptionStatus
