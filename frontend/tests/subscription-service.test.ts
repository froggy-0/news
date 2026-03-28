import test from "node:test";
import assert from "node:assert/strict";

import { SubscriptionService } from "../lib/subscriptions/service";
import { sha256Hex, signUnsubscribeToken } from "../lib/subscriptions/tokens";
import type {
  ConfirmationTokenRecord,
  SubscriptionEnv,
  SubscriptionRecord,
} from "../lib/subscriptions/types";

class FakeRepository {
  subscriptions = new Map<string, SubscriptionRecord>();
  confirmationTokens = new Map<string, ConfirmationTokenRecord>();

  async findByNormalizedEmail(newsletter: string, emailNormalized: string) {
    return (
      [...this.subscriptions.values()].find(
        (item) => item.newsletter === newsletter && item.emailNormalized === emailNormalized,
      ) ?? null
    );
  }

  async findById(id: string) {
    return this.subscriptions.get(id) ?? null;
  }

  async upsertPendingSubscription(input: {
    email: string;
    emailNormalized: string;
    newsletter: string;
  }) {
    const existing = await this.findByNormalizedEmail(input.newsletter, input.emailNormalized);
    const record: SubscriptionRecord = {
      id: existing?.id ?? `sub_${this.subscriptions.size + 1}`,
      email: input.email,
      emailNormalized: input.emailNormalized,
      newsletter: input.newsletter,
      status: "pending",
      subscribedAt: null,
      unsubscribedAt: null,
      bouncedAt: null,
      statusReason: "awaiting_confirmation",
      createdAt: existing?.createdAt ?? new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    this.subscriptions.set(record.id, record);
    return record;
  }

  async createConfirmationToken(input: {
    subscriberId: string;
    tokenHash: string;
    expiresAt: string;
  }) {
    const record: ConfirmationTokenRecord = {
      id: `token_${this.confirmationTokens.size + 1}`,
      subscriberId: input.subscriberId,
      tokenHash: input.tokenHash,
      tokenType: "confirm_subscription",
      expiresAt: input.expiresAt,
      consumedAt: null,
      createdAt: new Date().toISOString(),
    };
    this.confirmationTokens.set(record.id, record);
  }

  async findConfirmationToken(tokenHash: string) {
    return (
      [...this.confirmationTokens.values()].find((item) => item.tokenHash === tokenHash) ?? null
    );
  }

  async markTokenConsumed(tokenId: string) {
    const token = this.confirmationTokens.get(tokenId);
    if (!token) {
      throw new Error("token not found");
    }
    this.confirmationTokens.set(tokenId, { ...token, consumedAt: new Date().toISOString() });
  }

  async markActive(subscriptionId: string) {
    const subscription = this.subscriptions.get(subscriptionId);
    if (!subscription) {
      throw new Error("subscription not found");
    }
    const next = {
      ...subscription,
      status: "active" as const,
      statusReason: "confirmed",
      subscribedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    this.subscriptions.set(subscriptionId, next);
    return next;
  }

  async markUnsubscribed(subscriptionId: string) {
    const subscription = this.subscriptions.get(subscriptionId);
    if (!subscription) {
      throw new Error("subscription not found");
    }
    const next = {
      ...subscription,
      status: "unsubscribed" as const,
      statusReason: "user_unsubscribed",
      unsubscribedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    this.subscriptions.set(subscriptionId, next);
    return next;
  }
}

function env(): SubscriptionEnv {
  return {
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY: "service-role-key",
    PUBLIC_APP_BASE_URL: "https://brief.example.com",
    SUBSCRIPTION_TOKEN_SECRET: "token-secret",
    CONFIRMATION_GMAIL_CLIENT_ID: "client-id",
    CONFIRMATION_GMAIL_CLIENT_SECRET: "client-secret",
    CONFIRMATION_GMAIL_REFRESH_TOKEN: "refresh-token",
    CONFIRMATION_GMAIL_SENDER: "brief@example.com",
  };
}

test("requestSubscription creates pending subscription and sends confirmation mail", async () => {
  const repository = new FakeRepository();
  const sentMails: Array<{ to: string; subject: string; text: string; html: string }> = [];
  const service = new SubscriptionService(
    repository as never,
    env(),
    async (_env, input) => {
      sentMails.push(input);
    },
  );

  const result = await service.requestSubscription({ email: "reader@example.com" });

  assert.equal(result.status, "pending");
  assert.equal(sentMails.length, 1);
  assert.equal(sentMails[0].subject, "[SOVEREIGN BRIEF] 구독 확인이 필요합니다");
  assert.match(sentMails[0].text, /subscribe\/confirm\?token=/);
  assert.equal(repository.subscriptions.size, 1);
  assert.equal(repository.confirmationTokens.size, 1);
});

test("requestSubscription is idempotent for already active subscriber", async () => {
  const repository = new FakeRepository();
  repository.subscriptions.set("sub_1", {
    id: "sub_1",
    email: "reader@example.com",
    emailNormalized: "reader@example.com",
    newsletter: "morning-brief",
    status: "active",
    subscribedAt: new Date().toISOString(),
    unsubscribedAt: null,
    bouncedAt: null,
    statusReason: "confirmed",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });
  let sentMailCount = 0;
  const service = new SubscriptionService(
    repository as never,
    env(),
    async () => {
      sentMailCount += 1;
    },
  );

  const result = await service.requestSubscription({ email: "reader@example.com" });

  assert.equal(result.status, "already-active");
  assert.equal(sentMailCount, 0);
});

test("confirmSubscription activates pending subscriber and consumes token", async () => {
  const repository = new FakeRepository();
  const service = new SubscriptionService(repository as never, env(), async () => {});
  await service.requestSubscription({ email: "reader@example.com" });

  const token = [...repository.confirmationTokens.values()][0];
  const rawToken = "confirm-token";
  token.tokenHash = await sha256Hex(rawToken);
  repository.confirmationTokens.set(token.id, token);

  const result = await service.confirmSubscription(rawToken);

  assert.equal(result.status, "activated");
  assert.equal([...repository.subscriptions.values()][0]?.status, "active");
  assert.notEqual(repository.confirmationTokens.get(token.id)?.consumedAt, null);
});

test("confirmSubscription rejects expired or consumed token", async () => {
  const repository = new FakeRepository();
  const service = new SubscriptionService(repository as never, env(), async () => {});
  await service.requestSubscription({ email: "reader@example.com" });

  const token = [...repository.confirmationTokens.values()][0];
  const rawToken = "expired-token";
  token.tokenHash = await sha256Hex(rawToken);
  token.expiresAt = new Date(Date.now() - 60_000).toISOString();
  token.consumedAt = new Date().toISOString();
  repository.confirmationTokens.set(token.id, token);

  const result = await service.confirmSubscription(rawToken);

  assert.equal(result.status, "invalid-token");
});

test("requestSubscription propagates confirmation mail failure without activation", async () => {
  const repository = new FakeRepository();
  const service = new SubscriptionService(
    repository as never,
    env(),
    async () => {
      throw new Error("mail transport failed");
    },
  );

  await assert.rejects(
    () => service.requestSubscription({ email: "reader@example.com" }),
    /mail transport failed/,
  );
  assert.equal([...repository.subscriptions.values()][0]?.status, "pending");
});

test("unsubscribe preview and mutation validate signed token", async () => {
  const repository = new FakeRepository();
  const record: SubscriptionRecord = {
    id: "sub_1",
    email: "reader@example.com",
    emailNormalized: "reader@example.com",
    newsletter: "morning-brief",
    status: "active",
    subscribedAt: new Date().toISOString(),
    unsubscribedAt: null,
    bouncedAt: null,
    statusReason: "confirmed",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  repository.subscriptions.set(record.id, record);

  const token = await signUnsubscribeToken(
    {
      v: 1,
      sub: record.id,
      email: record.email,
      newsletter: record.newsletter,
      action: "unsubscribe",
      iat: Math.floor(Date.now() / 1000),
      exp: Math.floor(Date.now() / 1000) + 3600,
    },
    env().SUBSCRIPTION_TOKEN_SECRET,
  );
  const service = new SubscriptionService(repository as never, env(), async () => {});

  const preview = await service.previewUnsubscribe(token);
  const result = await service.unsubscribe(token);

  assert.equal(preview.status, "ready");
  assert.equal(result.status, "unsubscribed");
  assert.equal(repository.subscriptions.get(record.id)?.status, "unsubscribed");
});

test("unsubscribe rejects malformed token", async () => {
  const repository = new FakeRepository();
  const service = new SubscriptionService(repository as never, env(), async () => {});

  const preview = await service.previewUnsubscribe("bad-token");
  const result = await service.unsubscribe("bad-token");

  assert.equal(preview.status, "invalid-token");
  assert.equal(result.status, "invalid-token");
});

test("unsubscribe rejects expired signed token", async () => {
  const repository = new FakeRepository();
  const record: SubscriptionRecord = {
    id: "sub_2",
    email: "reader2@example.com",
    emailNormalized: "reader2@example.com",
    newsletter: "morning-brief",
    status: "active",
    subscribedAt: new Date().toISOString(),
    unsubscribedAt: null,
    bouncedAt: null,
    statusReason: "confirmed",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  repository.subscriptions.set(record.id, record);
  const service = new SubscriptionService(repository as never, env(), async () => {});

  const token = await signUnsubscribeToken(
    {
      v: 1,
      sub: record.id,
      email: record.email,
      newsletter: record.newsletter,
      action: "unsubscribe",
      iat: Math.floor(Date.now() / 1000) - 7200,
      exp: Math.floor(Date.now() / 1000) - 3600,
    },
    env().SUBSCRIPTION_TOKEN_SECRET,
  );

  const preview = await service.previewUnsubscribe(token);

  assert.equal(preview.status, "invalid-token");
});
