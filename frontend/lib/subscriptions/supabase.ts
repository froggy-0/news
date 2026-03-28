import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import type { SubscriptionEnv } from "./types";

export function createAdminSupabaseClient(env: Pick<SubscriptionEnv, "SUPABASE_URL" | "SUPABASE_SERVICE_ROLE_KEY">): SupabaseClient {
  return createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}
