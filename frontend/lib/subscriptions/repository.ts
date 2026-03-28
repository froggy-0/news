import type { SupabaseClient } from "@supabase/supabase-js";

import type { ConfirmationTokenRecord, SubscriptionRecord } from "./types";

function mapSubscriptionRecord(row: Record<string, unknown>): SubscriptionRecord {
  return {
    id: String(row.id),
    email: String(row.email),
    emailNormalized: String(row.email_normalized),
    newsletter: String(row.newsletter),
    status: String(row.status) as SubscriptionRecord["status"],
    subscribedAt: row.subscribed_at ? String(row.subscribed_at) : null,
    unsubscribedAt: row.unsubscribed_at ? String(row.unsubscribed_at) : null,
    bouncedAt: row.bounced_at ? String(row.bounced_at) : null,
    statusReason: row.status_reason ? String(row.status_reason) : null,
    createdAt: String(row.created_at),
    updatedAt: String(row.updated_at),
  };
}

function mapConfirmationTokenRecord(row: Record<string, unknown>): ConfirmationTokenRecord {
  return {
    id: String(row.id),
    subscriberId: String(row.subscriber_id),
    tokenHash: String(row.token_hash),
    tokenType: "confirm_subscription",
    expiresAt: String(row.expires_at),
    consumedAt: row.consumed_at ? String(row.consumed_at) : null,
    createdAt: String(row.created_at),
  };
}

export class SupabaseSubscriptionRepository {
  constructor(private readonly client: SupabaseClient) {}

  async findByNormalizedEmail(
    newsletter: string,
    emailNormalized: string,
  ): Promise<SubscriptionRecord | null> {
    const { data, error } = await this.client
      .from("subscriptions")
      .select("*")
      .eq("newsletter", newsletter)
      .eq("email_normalized", emailNormalized)
      .maybeSingle();
    if (error) {
      throw new Error(`Failed to load subscription: ${error.message}`);
    }
    return data ? mapSubscriptionRecord(data) : null;
  }

  async findById(id: string): Promise<SubscriptionRecord | null> {
    const { data, error } = await this.client.from("subscriptions").select("*").eq("id", id).maybeSingle();
    if (error) {
      throw new Error(`Failed to load subscription by id: ${error.message}`);
    }
    return data ? mapSubscriptionRecord(data) : null;
  }

  async upsertPendingSubscription(input: {
    email: string;
    emailNormalized: string;
    newsletter: string;
  }): Promise<SubscriptionRecord> {
    const now = new Date().toISOString();
    const { data, error } = await this.client
      .from("subscriptions")
      .upsert(
        {
          email: input.email,
          email_normalized: input.emailNormalized,
          newsletter: input.newsletter,
          status: "pending",
          status_reason: "awaiting_confirmation",
          unsubscribed_at: null,
          bounced_at: null,
          updated_at: now,
        },
        {
          onConflict: "newsletter,email_normalized",
        },
      )
      .select("*")
      .single();
    if (error) {
      throw new Error(`Failed to upsert subscription: ${error.message}`);
    }
    return mapSubscriptionRecord(data);
  }

  async createConfirmationToken(input: {
    subscriberId: string;
    tokenHash: string;
    expiresAt: string;
  }): Promise<void> {
    const { error } = await this.client.from("subscription_tokens").insert({
      subscriber_id: input.subscriberId,
      token_hash: input.tokenHash,
      token_type: "confirm_subscription",
      expires_at: input.expiresAt,
    });
    if (error) {
      throw new Error(`Failed to create confirmation token: ${error.message}`);
    }
  }

  async findConfirmationToken(tokenHash: string): Promise<ConfirmationTokenRecord | null> {
    const { data, error } = await this.client
      .from("subscription_tokens")
      .select("*")
      .eq("token_hash", tokenHash)
      .eq("token_type", "confirm_subscription")
      .maybeSingle();
    if (error) {
      throw new Error(`Failed to load confirmation token: ${error.message}`);
    }
    return data ? mapConfirmationTokenRecord(data) : null;
  }

  async markTokenConsumed(tokenId: string): Promise<void> {
    const { error } = await this.client
      .from("subscription_tokens")
      .update({ consumed_at: new Date().toISOString() })
      .eq("id", tokenId);
    if (error) {
      throw new Error(`Failed to consume token: ${error.message}`);
    }
  }

  async markActive(subscriptionId: string): Promise<SubscriptionRecord> {
    const now = new Date().toISOString();
    const { data, error } = await this.client
      .from("subscriptions")
      .update({
        status: "active",
        status_reason: "confirmed",
        subscribed_at: now,
        unsubscribed_at: null,
        updated_at: now,
      })
      .eq("id", subscriptionId)
      .select("*")
      .single();
    if (error) {
      throw new Error(`Failed to activate subscription: ${error.message}`);
    }
    return mapSubscriptionRecord(data);
  }

  async markUnsubscribed(subscriptionId: string): Promise<SubscriptionRecord> {
    const now = new Date().toISOString();
    const { data, error } = await this.client
      .from("subscriptions")
      .update({
        status: "unsubscribed",
        status_reason: "user_unsubscribed",
        unsubscribed_at: now,
        updated_at: now,
      })
      .eq("id", subscriptionId)
      .select("*")
      .single();
    if (error) {
      throw new Error(`Failed to unsubscribe subscription: ${error.message}`);
    }
    return mapSubscriptionRecord(data);
  }
}
