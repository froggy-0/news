import {
  SendEmailCommand,
  type SendEmailCommandInput,
  SESv2Client,
} from "@aws-sdk/client-sesv2";

import type { SubscriptionEnv } from "./types";

const REQUIRED_REGION = "ap-northeast-2";
const REQUIRED_SENDER = "no-reply@sovereignbriefing.com";

function classifyConfirmationSesError(error: unknown): {
  category: "auth_failure" | "identity_failure" | "recipient_failure" | "delivery_failure";
  detail: string;
} {
  const name = error instanceof Error ? error.name : "UnknownSesError";
  const message = error instanceof Error ? error.message : "unknown SES error";
  const normalized = `${name} ${message}`.toLowerCase();

  if (
    ["AccessDenied", "AccessDeniedException", "InvalidClientTokenId"].includes(name) ||
    normalized.includes("security token") ||
    normalized.includes("access denied") ||
    normalized.includes("signature") ||
    normalized.includes("not authorized")
  ) {
    return { category: "auth_failure", detail: `${name}: ${message}` };
  }

  if (
    ["MailFromDomainNotVerifiedException", "ConfigurationSetDoesNotExistException"].includes(
      name,
    ) ||
    normalized.includes("not verified") ||
    normalized.includes("identity") ||
    normalized.includes("mail from domain") ||
    normalized.includes("configuration set")
  ) {
    return { category: "identity_failure", detail: `${name}: ${message}` };
  }

  if (
    normalized.includes("recipient") ||
    normalized.includes("destination") ||
    normalized.includes("address") ||
    normalized.includes("blacklist") ||
    normalized.includes("suppression")
  ) {
    return { category: "recipient_failure", detail: `${name}: ${message}` };
  }

  return { category: "delivery_failure", detail: `${name}: ${message}` };
}

function requireEnvValue(value: string, name: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`${name} is required for SES delivery`);
  }
  return trimmed;
}

function configuredRegion(env: SubscriptionEnv): string {
  const region = requireEnvValue(env.AWS_REGION, "AWS_REGION");
  if (region !== REQUIRED_REGION) {
    throw new Error(`AWS_REGION must be ${REQUIRED_REGION}, got ${region}`);
  }
  return region;
}

function configuredSender(env: SubscriptionEnv): string {
  const sender = requireEnvValue(env.CONFIRMATION_SES_SENDER, "CONFIRMATION_SES_SENDER");
  if (sender !== REQUIRED_SENDER) {
    throw new Error(`CONFIRMATION_SES_SENDER must be ${REQUIRED_SENDER}, got ${sender}`);
  }
  return sender;
}

export function buildConfirmationEmailRequest(
  env: SubscriptionEnv,
  input: { to: string; subject: string; text: string; html: string },
): SendEmailCommandInput {
  return {
    FromEmailAddress: configuredSender(env),
    Destination: {
      ToAddresses: [input.to],
    },
    Content: {
      Simple: {
        Subject: {
          Data: input.subject,
          Charset: "UTF-8",
        },
        Body: {
          Text: {
            Data: input.text,
            Charset: "UTF-8",
          },
          Html: {
            Data: input.html,
            Charset: "UTF-8",
          },
        },
      },
    },
  };
}

export function createConfirmationSesClient(env: SubscriptionEnv): SESv2Client {
  return new SESv2Client({
    region: configuredRegion(env),
    credentials: {
      accessKeyId: requireEnvValue(env.AWS_ACCESS_KEY_ID, "AWS_ACCESS_KEY_ID"),
      secretAccessKey: requireEnvValue(env.AWS_SECRET_ACCESS_KEY, "AWS_SECRET_ACCESS_KEY"),
    },
  });
}

export async function sendConfirmationMail(
  env: SubscriptionEnv,
  input: { to: string; subject: string; text: string; html: string },
): Promise<void> {
  const client = createConfirmationSesClient(env);
  try {
    await client.send(new SendEmailCommand(buildConfirmationEmailRequest(env, input)));
  } catch (error) {
    const failure = classifyConfirmationSesError(error);
    throw new Error(`Failed to send confirmation mail (${failure.category}): ${failure.detail}`);
  } finally {
    client.destroy();
  }
}
