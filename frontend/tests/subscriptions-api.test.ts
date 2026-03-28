import test from "node:test";
import assert from "node:assert/strict";

import { onRequestGet as confirmGet, onRequestPost as confirmPost } from "../functions/api/subscriptions/confirm";
import { onRequestPost as requestPost } from "../functions/api/subscriptions/request";
import {
  onRequestGet as unsubscribeGet,
  onRequestPost as unsubscribePost,
} from "../functions/api/subscriptions/unsubscribe";

const env = {
  SUPABASE_URL: "https://example.supabase.co",
  SUPABASE_SERVICE_ROLE_KEY: "service-role-key",
  PUBLIC_APP_BASE_URL: "https://brief.example.com",
  SUBSCRIPTION_TOKEN_SECRET: "token-secret",
  CONFIRMATION_GMAIL_CLIENT_ID: "client-id",
  CONFIRMATION_GMAIL_CLIENT_SECRET: "client-secret",
  CONFIRMATION_GMAIL_REFRESH_TOKEN: "refresh-token",
  CONFIRMATION_GMAIL_SENDER: "brief@example.com",
};

test("request route returns 400 on invalid email payload", async () => {
  const response = await requestPost({
    request: new Request("https://brief.example.com/api/subscriptions/request", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: "bad-email" }),
    }),
    env,
  });

  assert.equal(response.status, 400);
});

test("confirm routes return 400 on missing token", async () => {
  const getResponse = await confirmGet({
    request: new Request("https://brief.example.com/api/subscriptions/confirm"),
    env,
  });
  const postResponse = await confirmPost({
    request: new Request("https://brief.example.com/api/subscriptions/confirm", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token: "" }),
    }),
    env,
  });

  assert.equal(getResponse.status, 400);
  assert.equal(postResponse.status, 400);
});

test("unsubscribe routes return 400 on invalid token", async () => {
  const getResponse = await unsubscribeGet({
    request: new Request("https://brief.example.com/api/subscriptions/unsubscribe?token=bad"),
    env,
  });
  const postResponse = await unsubscribePost({
    request: new Request("https://brief.example.com/api/subscriptions/unsubscribe", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token: "bad" }),
    }),
    env,
  });

  assert.equal(getResponse.status, 400);
  assert.equal(postResponse.status, 400);
});
