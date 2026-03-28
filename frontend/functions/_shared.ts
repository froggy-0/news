import { createAdminSupabaseClient } from "@/lib/subscriptions/supabase";
import { SupabaseSubscriptionRepository } from "@/lib/subscriptions/repository";
import { SubscriptionService } from "@/lib/subscriptions/service";
import type { SubscriptionEnv } from "@/lib/subscriptions/types";

export interface PagesContext<Env> {
  request: Request;
  env: Env;
}

export type PagesFunction<Env> = (context: PagesContext<Env>) => Promise<Response> | Response;

export function json(data: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...(init?.headers ?? {}),
    },
  });
}

export function createSubscriptionService(env: SubscriptionEnv): SubscriptionService {
  const client = createAdminSupabaseClient(env);
  const repository = new SupabaseSubscriptionRepository(client);
  return new SubscriptionService(repository, env);
}
