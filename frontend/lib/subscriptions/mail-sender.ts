import type { SubscriptionEnv } from "./types";

function encodeBase64Url(value: string): string {
  let binary = "";
  for (const byte of new TextEncoder().encode(value)) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/gu, "-").replace(/\//gu, "_").replace(/=+$/u, "");
}

async function fetchAccessToken(env: SubscriptionEnv): Promise<string> {
  const body = new URLSearchParams({
    client_id: env.CONFIRMATION_GMAIL_CLIENT_ID,
    client_secret: env.CONFIRMATION_GMAIL_CLIENT_SECRET,
    refresh_token: env.CONFIRMATION_GMAIL_REFRESH_TOKEN,
    grant_type: "refresh_token",
  });

  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
    },
    body,
  });
  if (!response.ok) {
    throw new Error(`Failed to refresh Gmail access token: ${response.status}`);
  }
  const payload = (await response.json()) as { access_token?: string };
  if (!payload.access_token) {
    throw new Error("Gmail access token response did not include access_token");
  }
  return payload.access_token;
}

function buildRawMessage(input: {
  from: string;
  to: string;
  subject: string;
  text: string;
  html: string;
}): string {
  const boundary = `boundary_${crypto.randomUUID()}`;
  const lines = [
    `From: ${input.from}`,
    `To: ${input.to}`,
    `Subject: ${input.subject}`,
    "MIME-Version: 1.0",
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
    "",
    `--${boundary}`,
    "Content-Type: text/plain; charset=UTF-8",
    "",
    input.text,
    "",
    `--${boundary}`,
    "Content-Type: text/html; charset=UTF-8",
    "",
    input.html,
    "",
    `--${boundary}--`,
  ];
  return encodeBase64Url(lines.join("\r\n"));
}

export async function sendConfirmationMail(
  env: SubscriptionEnv,
  input: { to: string; subject: string; text: string; html: string },
): Promise<void> {
  const accessToken = await fetchAccessToken(env);
  const raw = buildRawMessage({
    from: env.CONFIRMATION_GMAIL_SENDER,
    to: input.to,
    subject: input.subject,
    text: input.text,
    html: input.html,
  });

  const response = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: {
      authorization: `Bearer ${accessToken}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ raw }),
  });
  if (!response.ok) {
    throw new Error(`Failed to send confirmation mail: ${response.status}`);
  }
}
