"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { SubscriptionState } from "@/components/ui/SubscriptionState";
import type { UnsubscribePayload, UnsubscribePreviewResponse, UnsubscribeResponse } from "@/lib/subscriptions/contracts";
import type { UnsubscribePreviewResult, UnsubscribeResult } from "@/lib/subscriptions/types";

export function UnsubscribeResult() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [preview, setPreview] = useState<UnsubscribePreviewResult | null>(null);
  const [result, setResult] = useState<UnsubscribeResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadPreview() {
      try {
        const response = await fetch(
          `/api/subscriptions/unsubscribe?token=${encodeURIComponent(token)}`,
        );
        const payload = (await response.json()) as UnsubscribePreviewResponse;
        if (!cancelled) {
          setPreview(
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
          setPreview({
            status: "invalid-token",
            message: "구독 해지 링크를 확인하지 못했습니다.",
          });
        }
      }
    }

    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleUnsubscribe() {
    setSubmitting(true);
    try {
      const response = await fetch("/api/subscriptions/unsubscribe", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({ token } satisfies UnsubscribePayload),
      });
      const payload = (await response.json()) as UnsubscribeResponse;
      setResult(
        "error" in payload
          ? {
              status: "invalid-token",
              message: payload.error,
            }
          : payload,
      );
    } catch {
      setResult({
        status: "invalid-token",
        message: "구독 해지 요청을 처리하지 못했습니다.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  const visibleState = result ?? preview;

  return (
    <section className="panel panel-soft space-y-4">
      <p className="section-title">unsubscribe</p>
      <h1 className="section-headline max-w-3xl">구독 해지</h1>
      <SubscriptionState
        tone={
          visibleState?.status === "invalid-token"
            ? "danger"
            : visibleState?.status === "unsubscribed" || visibleState?.status === "already-unsubscribed"
              ? "success"
              : "neutral"
        }
      >
        <div className="copy-block">
          <p>{visibleState?.message ?? "구독 상태를 확인하는 중입니다."}</p>
          {visibleState?.email ? <p className="numeric">{visibleState.email}</p> : null}
        </div>
      </SubscriptionState>
      {!result && preview?.status === "ready" ? (
        <button
          type="button"
          onClick={handleUnsubscribe}
          disabled={submitting}
          className="min-h-[48px] rounded-full border border-white/12 bg-white/5 px-5 py-3 font-mono text-[11px] tracking-[0.18em] text-[var(--text-primary)] transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "처리 중" : "이 이메일 구독 해지"}
        </button>
      ) : null}
    </section>
  );
}
