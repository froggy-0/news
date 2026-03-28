import type { SubscriptionEnv } from "@/lib/subscriptions/types";
import type { RequestSubscriptionPayload } from "@/lib/subscriptions/contracts";

import { createSubscriptionService, json, type PagesFunction } from "../../_shared";

export const onRequestPost: PagesFunction<SubscriptionEnv> = async ({ request, env }) => {
  try {
    const payload = (await request.json()) as Partial<RequestSubscriptionPayload>;
    const service = createSubscriptionService(env);
    const result = await service.requestSubscription({ email: payload.email ?? "" });
    return json(result);
  } catch (error) {
    return json(
      {
        error: error instanceof Error ? error.message : "구독 요청 처리 중 오류가 발생했습니다.",
      },
      { status: 400 },
    );
  }
};
