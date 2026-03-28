import { buildConfirmationMail } from "./confirmation-mail";
import { sendConfirmationMail } from "./mail-sender";
import { SupabaseSubscriptionRepository } from "./repository";
import { randomToken, sha256Hex, verifyUnsubscribeToken } from "./tokens";
import type {
  ConfirmSubscriptionResult,
  RequestSubscriptionResult,
  SubscriptionEnv,
  SubscriptionRecord,
  UnsubscribePreviewResult,
  UnsubscribeResult,
} from "./types";
import { isValidEmail, normalizeEmail } from "./validation";

const CONFIRM_TOKEN_TTL_MS = 1000 * 60 * 60 * 24;
const NEWSLETTER_KEY = "morning-brief";

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/$/u, "");
}

export class SubscriptionService {
  constructor(
    private readonly repository: SupabaseSubscriptionRepository,
    private readonly env: SubscriptionEnv,
    private readonly sendMail: typeof sendConfirmationMail = sendConfirmationMail,
  ) {}

  async requestSubscription(input: {
    email: string;
    baseUrl?: string;
  }): Promise<RequestSubscriptionResult> {
    if (!isValidEmail(input.email)) {
      throw new Error("유효한 이메일 주소를 입력해 주세요.");
    }

    const newsletter = NEWSLETTER_KEY;
    const emailNormalized = normalizeEmail(input.email);
    const existing = await this.repository.findByNormalizedEmail(newsletter, emailNormalized);
    if (existing?.status === "active") {
      return {
        status: "already-active",
        message: "이미 구독 중인 이메일입니다.",
      };
    }

    const subscription = await this.repository.upsertPendingSubscription({
      email: input.email.trim(),
      emailNormalized,
      newsletter,
    });

    const rawToken = randomToken();
    const tokenHash = await sha256Hex(rawToken);
    const expiresAt = new Date(Date.now() + CONFIRM_TOKEN_TTL_MS).toISOString();
    await this.repository.createConfirmationToken({
      subscriberId: subscription.id,
      tokenHash,
      expiresAt,
    });

    const baseUrl = normalizeBaseUrl(input.baseUrl ?? this.env.PUBLIC_APP_BASE_URL);
    const confirmUrl = `${baseUrl}/subscribe/confirm?token=${encodeURIComponent(rawToken)}`;
    const mail = buildConfirmationMail({ confirmUrl });
    await this.sendMail(this.env, {
      to: subscription.email,
      subject: mail.subject,
      text: mail.text,
      html: mail.html,
    });

    return {
      status: "pending",
      message: "확인 메일을 보냈습니다. 메일함에서 링크를 눌러 구독을 완료해 주세요.",
    };
  }

  async confirmSubscription(token: string): Promise<ConfirmSubscriptionResult> {
    if (!token) {
      return { status: "invalid-token", message: "확인 링크가 올바르지 않습니다." };
    }

    const tokenHash = await sha256Hex(token);
    const record = await this.repository.findConfirmationToken(tokenHash);
    if (!record || record.consumedAt || Date.parse(record.expiresAt) < Date.now()) {
      return { status: "invalid-token", message: "확인 링크가 만료되었거나 이미 사용되었습니다." };
    }

    const subscription = await this.repository.findById(record.subscriberId);
    if (!subscription) {
      return { status: "invalid-token", message: "구독 정보를 찾을 수 없습니다." };
    }
    if (subscription.status === "active") {
      await this.repository.markTokenConsumed(record.id);
      return { status: "already-active", message: "이미 구독이 활성화되어 있습니다." };
    }

    await this.repository.markActive(subscription.id);
    await this.repository.markTokenConsumed(record.id);
    return { status: "activated", message: "구독이 활성화되었습니다. 다음 발송부터 받아보실 수 있습니다." };
  }

  async previewUnsubscribe(token: string): Promise<UnsubscribePreviewResult> {
    const payload = await verifyUnsubscribeToken(token, this.env.SUBSCRIPTION_TOKEN_SECRET);
    if (!payload) {
      return { status: "invalid-token", message: "구독 해지 링크가 올바르지 않습니다." };
    }

    const subscription = await this.repository.findById(payload.sub);
    if (!this.matchesUnsubscribePayload(subscription, payload.email, payload.newsletter)) {
      return { status: "invalid-token", message: "구독 해지 링크가 더 이상 유효하지 않습니다." };
    }
    if (subscription.status === "unsubscribed") {
      return {
        status: "already-unsubscribed",
        message: "이미 구독 해지가 완료된 이메일입니다.",
        email: subscription.email,
      };
    }
    return {
      status: "ready",
      message: "이 이메일 주소를 다음 발송부터 제외할 수 있습니다.",
      email: subscription.email,
    };
  }

  async unsubscribe(token: string): Promise<UnsubscribeResult> {
    const preview = await this.previewUnsubscribe(token);
    if (preview.status === "invalid-token") {
      return { status: "invalid-token", message: preview.message };
    }
    if (preview.status === "already-unsubscribed") {
      return {
        status: "already-unsubscribed",
        message: preview.message,
        email: preview.email,
      };
    }

    const payload = await verifyUnsubscribeToken(token, this.env.SUBSCRIPTION_TOKEN_SECRET);
    if (!payload) {
      return { status: "invalid-token", message: "구독 해지 링크가 올바르지 않습니다." };
    }

    await this.repository.markUnsubscribed(payload.sub);
    return {
      status: "unsubscribed",
      message: "구독 해지가 완료되었습니다. 이후 브리핑 메일은 발송되지 않습니다.",
      email: preview.email,
    };
  }

  private matchesUnsubscribePayload(
    subscription: SubscriptionRecord | null,
    email: string,
    newsletter: string,
  ): subscription is SubscriptionRecord {
    return Boolean(
      subscription &&
        subscription.emailNormalized === normalizeEmail(email) &&
        subscription.newsletter === newsletter,
    );
  }
}
