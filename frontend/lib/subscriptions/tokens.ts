const encoder = new TextEncoder();
const decoder = new TextDecoder();

export interface UnsubscribeTokenPayload {
  v: number;
  sub: string;
  email: string;
  newsletter: string;
  action: "unsubscribe";
  iat: number;
  exp: number;
}

function stripBase64Padding(value: string): string {
  return value.replace(/=+$/u, "");
}

function toBase64Url(data: Uint8Array): string {
  let binary = "";
  for (const byte of data) {
    binary += String.fromCharCode(byte);
  }
  return stripBase64Padding(btoa(binary)).replace(/\+/gu, "-").replace(/\//gu, "_");
}

function fromBase64Url(value: string): Uint8Array {
  const padded = value.replace(/-/gu, "+").replace(/_/gu, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

async function hmacSignature(secret: string, payloadBytes: Uint8Array): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret) as BufferSource,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, payloadBytes as BufferSource);
  return toBase64Url(new Uint8Array(signature));
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value) as BufferSource);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function randomToken(): string {
  return toBase64Url(crypto.getRandomValues(new Uint8Array(32)));
}

export async function signUnsubscribeToken(
  payload: UnsubscribeTokenPayload,
  secret: string,
): Promise<string> {
  const payloadBytes = encoder.encode(JSON.stringify(payload));
  const signature = await hmacSignature(secret, payloadBytes);
  return `${toBase64Url(payloadBytes)}.${signature}`;
}

export async function verifyUnsubscribeToken(
  token: string,
  secret: string,
): Promise<UnsubscribeTokenPayload | null> {
  const [encodedPayload, encodedSignature] = token.split(".");
  if (!encodedPayload || !encodedSignature) {
    return null;
  }

  const payloadBytes = fromBase64Url(encodedPayload);
  const expectedSignature = await hmacSignature(secret, payloadBytes);
  if (expectedSignature !== encodedSignature) {
    return null;
  }

  const payload = JSON.parse(decoder.decode(payloadBytes)) as Partial<UnsubscribeTokenPayload>;
  if (
    payload.v !== 1 ||
    payload.action !== "unsubscribe" ||
    typeof payload.sub !== "string" ||
    typeof payload.email !== "string" ||
    typeof payload.newsletter !== "string" ||
    typeof payload.iat !== "number" ||
    typeof payload.exp !== "number"
  ) {
    return null;
  }
  if (payload.exp <= Math.floor(Date.now() / 1000)) {
    return null;
  }

  return {
    v: 1,
    sub: payload.sub,
    email: payload.email,
    newsletter: payload.newsletter,
    action: "unsubscribe",
    iat: payload.iat,
    exp: payload.exp,
  };
}
