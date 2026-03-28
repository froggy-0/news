import type { SubscriptionEnv } from "@/lib/subscriptions/types";
import type { UnsubscribePayload } from "@/lib/subscriptions/contracts";

import { createSubscriptionService, json, type PagesFunction } from "../../_shared";

function tokenFromRequest(request: Request): string {
  const url = new URL(request.url);
  return url.searchParams.get("token") ?? "";
}

export const onRequestGet: PagesFunction<SubscriptionEnv> = async ({ request, env }) => {
  const service = createSubscriptionService(env);
  const result = await service.previewUnsubscribe(tokenFromRequest(request));
  return json(result, { status: result.status === "invalid-token" ? 400 : 200 });
};

export const onRequestPost: PagesFunction<SubscriptionEnv> = async ({ request, env }) => {
  const payload = (await request.json()) as Partial<UnsubscribePayload>;
  const service = createSubscriptionService(env);
  const result = await service.unsubscribe(payload.token ?? "");
  return json(result, { status: result.status === "invalid-token" ? 400 : 200 });
};
