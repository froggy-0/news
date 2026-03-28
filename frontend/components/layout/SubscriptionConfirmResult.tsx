"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { SubscriptionState } from "@/components/ui/SubscriptionState";
import type { ConfirmSubscriptionResponse } from "@/lib/subscriptions/contracts";
import type { ConfirmSubscriptionResult } from "@/lib/subscriptions/types";

function initialState(): ConfirmSubscriptionResult {
  return {
    status: "invalid-token",
    message: "확인 링크를 확인하는 중입니다.",
  };
}

export function SubscriptionConfirmResult() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [state, setState] = useState<ConfirmSubscriptionResult>(initialState);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const response = await fetch(`/api/subscriptions/confirm?token=${encodeURIComponent(token)}`);
        const payload = (await response.json()) as ConfirmSubscriptionResponse;
        if (!cancelled) {
          setState(
            "error" in payload
              ? {
                  status: "invalid-token",
                  message: payload.error,
                }
              : payload,
          );
        }
      } catch {
        if (!cancelled) {
          setState({
            status: "invalid-token",
            message: "확인 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
          });
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <section className="panel panel-soft space-y-4">
      <p className="section-title">subscription confirm</p>
      <h1 className="section-headline max-w-3xl">
        {loading ? "구독 확인 중입니다" : "구독 확인 결과"}
      </h1>
      <SubscriptionState tone={state.status === "invalid-token" ? "danger" : "success"}>
        <div className="copy-block">
          <p>{state.message}</p>
        </div>
      </SubscriptionState>
    </section>
  );
}
