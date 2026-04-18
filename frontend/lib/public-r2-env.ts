const PUBLIC_R2_BASE_URL_ENV = "NEXT_PUBLIC_R2_BASE_URL";
const LEGACY_PUBLIC_R2_BASE_URL_ENV = "R2_BASE_URL";

type EnvMap = Record<string, string | undefined>;

function normalizeEnvValue(value: string | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed ? trimmed : null;
}

export function resolvePublicR2BaseUrl(env: EnvMap = process.env): string | null {
  return (
    normalizeEnvValue(env[PUBLIC_R2_BASE_URL_ENV]) ??
    normalizeEnvValue(env[LEGACY_PUBLIC_R2_BASE_URL_ENV])
  );
}

export function requireAbsoluteHttpUrl(value: string, envName: string): string {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error("invalid protocol");
    }
    return value.replace(/\/$/, "");
  } catch {
    throw new Error(`${envName} must be an absolute http(s) URL. Received: ${value}`);
  }
}

export { LEGACY_PUBLIC_R2_BASE_URL_ENV, PUBLIC_R2_BASE_URL_ENV };
