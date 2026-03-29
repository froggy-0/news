import test from "node:test";
import assert from "node:assert/strict";
import { SESv2Client } from "@aws-sdk/client-sesv2";

import {
  buildConfirmationEmailRequest,
  createConfirmationSesClient,
  sendConfirmationMail,
} from "../lib/subscriptions/mail-sender";
import type { SubscriptionEnv } from "../lib/subscriptions/types";

function env(): SubscriptionEnv {
  return {
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY: "service-role-key",
    PUBLIC_APP_BASE_URL: "https://brief.example.com",
    SUBSCRIPTION_TOKEN_SECRET: "token-secret",
    AWS_ACCESS_KEY_ID: "test-access-key",
    AWS_SECRET_ACCESS_KEY: "test-secret-key",
    AWS_REGION: "ap-northeast-2",
    CONFIRMATION_SES_SENDER: "no-reply@sovereignbriefing.com",
  };
}

test("buildConfirmationEmailRequest uses the configured sender and preserves content", () => {
  const request = buildConfirmationEmailRequest(env(), {
    to: "reader@example.com",
    subject: "[SOVEREIGN BRIEF] 구독 확인이 필요합니다",
    text: "텍스트 본문",
    html: "<p>HTML 본문</p>",
  });

  assert.equal(request.FromEmailAddress, "no-reply@sovereignbriefing.com");
  assert.deepEqual(request.Destination?.ToAddresses, ["reader@example.com"]);
  assert.equal(request.Content?.Simple?.Subject?.Data, "[SOVEREIGN BRIEF] 구독 확인이 필요합니다");
  assert.equal(request.Content?.Simple?.Body?.Text?.Data, "텍스트 본문");
  assert.equal(request.Content?.Simple?.Body?.Html?.Data, "<p>HTML 본문</p>");
});

test("createConfirmationSesClient rejects unsupported region", () => {
  assert.throws(
    () =>
      createConfirmationSesClient({
        ...env(),
        AWS_REGION: "us-east-1",
      }),
    /AWS_REGION must be ap-northeast-2/,
  );
});

test("buildConfirmationEmailRequest rejects missing sender secret", () => {
  assert.throws(
    () =>
      buildConfirmationEmailRequest(
        {
          ...env(),
          CONFIRMATION_SES_SENDER: "",
        },
        {
          to: "reader@example.com",
          subject: "제목",
          text: "본문",
          html: "<p>본문</p>",
        },
      ),
    /CONFIRMATION_SES_SENDER is required/,
  );
});

test("sendConfirmationMail surfaces auth_failure when credentials are rejected", async () => {
  const originalSend = SESv2Client.prototype.send;
  SESv2Client.prototype.send = (async function mockedSend() {
    const error = new Error("The security token included in the request is invalid.");
    error.name = "AccessDeniedException";
    throw error;
  }) as typeof SESv2Client.prototype.send;

  try {
    await assert.rejects(
      () =>
        sendConfirmationMail(env(), {
          to: "reader@example.com",
          subject: "제목",
          text: "본문",
          html: "<p>본문</p>",
        }),
      /auth_failure/,
    );
  } finally {
    SESv2Client.prototype.send = originalSend;
  }
});

test("sendConfirmationMail surfaces identity_failure for unverified sender errors", async () => {
  const originalSend = SESv2Client.prototype.send;
  SESv2Client.prototype.send = (async function mockedSend() {
    const error = new Error("Email address is not verified.");
    error.name = "MessageRejected";
    throw error;
  }) as typeof SESv2Client.prototype.send;

  try {
    await assert.rejects(
      () =>
        sendConfirmationMail(env(), {
          to: "reader@example.com",
          subject: "제목",
          text: "본문",
          html: "<p>본문</p>",
        }),
      /identity_failure/,
    );
  } finally {
    SESv2Client.prototype.send = originalSend;
  }
});
