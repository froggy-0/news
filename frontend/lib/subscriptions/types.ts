export type SubscriptionStatus = "pending" | "active" | "unsubscribed" | "bounced";

export interface SubscriptionRecord {
  id: string;
  email: string;
  emailNormalized: string;
  newsletter: string;
  status: SubscriptionStatus;
  subscribedAt: string | null;
  unsubscribedAt: string | null;
  bouncedAt: string | null;
  statusReason: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ConfirmationTokenRecord {
  id: string;
  subscriberId: string;
  tokenHash: string;
  tokenType: "confirm_subscription";
  expiresAt: string;
  consumedAt: string | null;
  createdAt: string;
}

export interface RequestSubscriptionResult {
  status: "pending" | "already-active";
  message: string;
}

export interface ConfirmSubscriptionResult {
  status: "activated" | "already-active" | "invalid-token";
  message: string;
}

export interface UnsubscribePreviewResult {
  status: "ready" | "already-unsubscribed" | "invalid-token";
  message: string;
  email?: string;
}

export interface UnsubscribeResult {
  status: "unsubscribed" | "already-unsubscribed" | "invalid-token";
  message: string;
  email?: string;
}

export interface SubscriptionEnv {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  PUBLIC_APP_BASE_URL: string;
  SUBSCRIPTION_TOKEN_SECRET: string;
  AWS_ACCESS_KEY_ID: string;
  AWS_SECRET_ACCESS_KEY: string;
  AWS_REGION: string;
  SES_SENDER?: string;
  CONFIRMATION_SES_SENDER?: string;
}
