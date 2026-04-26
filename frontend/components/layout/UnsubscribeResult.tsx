"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, Loader2, MailX, ShieldAlert } from "lucide-react";

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
            message: "Could not verify the unsubscribe link.",
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
        message: "Failed to process the unsubscribe request.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  const loading = preview === null;
  const activeState = result ?? preview;
  const isError = activeState?.status === "invalid-token";
  const isSuccess =
    activeState?.status === "unsubscribed" || activeState?.status === "already-unsubscribed";
  const isReady = !loading && !isError && !isSuccess;

  const headline = loading
    ? "Verifying your unsubscribe link..."
    : isSuccess
      ? "Unsubscribed successfully."
      : isReady
        ? "Confirm unsubscribe?"
        : "Please check your unsubscribe link.";

  const subCopy = loading
    ? "Checking link validity and subscription status..."
    : isSuccess
      ? "You will no longer receive SOVEREIGN BRIEF from the next send."
      : isReady
        ? "Click the button below to stop receiving emails immediately."
        : "If the link has expired or already been used, contact us directly by email.";

  const badge = submitting
    ? "processing"
    : loading
      ? "checking"
      : isSuccess
        ? "unsubscribed"
        : isReady
          ? "ready"
          : "action needed";

  const iconClass = loading || submitting
    ? "border-white/12 bg-white/[0.03] text-white/68"
    : isSuccess
      ? "border-[#00ff66]/25 bg-[#00ff66]/10 text-[#00ff66]"
      : isReady
        ? "border-white/12 bg-white/[0.03] text-white/68"
        : "border-[#ff6b6b]/25 bg-[#ff6b6b]/10 text-[#ff6b6b]";

  const badgeClass = loading || submitting
    ? "border-white/12 text-white/52"
    : isSuccess
      ? "border-[#00ff66]/25 text-[#00ff66]"
      : isReady
        ? "border-white/12 text-white/52"
        : "border-[#ff6b6b]/25 text-[#ff6b6b]";

  return (
    <section className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <div className="space-y-3">
        <p className="section-title">unsubscribe</p>
        <h1 className="section-headline max-w-3xl">{headline}</h1>
        <p className="copy-block max-w-2xl">{subCopy}</p>
      </div>

      <div className="section-shell rounded-[32px] p-6 md:p-8">
        <div className="mb-6 flex items-start justify-between gap-4 border-b border-white/8 pb-6">
          <div className="flex items-start gap-4">
            <div
              className={`mt-0.5 flex h-12 w-12 items-center justify-center rounded-full border ${iconClass}`}
            >
              {loading || submitting ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : isSuccess ? (
                <CheckCircle2 className="h-5 w-5" />
              ) : isReady ? (
                <MailX className="h-5 w-5" />
              ) : (
                <ShieldAlert className="h-5 w-5" />
              )}
            </div>
            <div className="space-y-2">
              <p className="text-[10px] font-mono uppercase tracking-[0.24em] text-white/34">
                Subscription Status
              </p>
              <h2 className="text-xl tracking-tight text-white">
                {submitting
                  ? "Processing..."
                  : loading
                    ? "Checking..."
                    : isSuccess
                      ? "Unsubscribed"
                      : isReady
                        ? "Ready"
                        : "Verification Failed"}
              </h2>
            </div>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-[10px] font-mono uppercase tracking-[0.2em] ${badgeClass}`}
          >
            {badge}
          </span>
        </div>

        <SubscriptionState
          tone={isError ? "danger" : isSuccess ? "success" : "neutral"}
        >
          <div className="copy-block">
            <p>{activeState?.message ?? "Checking subscription status..."}</p>
            {activeState?.email ? <p className="numeric">{activeState.email}</p> : null}
          </div>
        </SubscriptionState>

        {isReady && !result ? (
          <div className="mt-6 grid gap-3 md:grid-cols-2">
            <Link
              href="/"
              className="inline-flex items-center justify-center gap-2 rounded-full border border-white/10 px-5 py-3 text-sm tracking-tight text-white/72 transition hover:border-white/24 hover:text-white"
            >
              Cancel
            </Link>
            <button
              type="button"
              onClick={handleUnsubscribe}
              disabled={submitting}
              className="inline-flex items-center justify-center gap-2 rounded-full border border-[#ff6b6b]/30 bg-[#ff6b6b]/10 px-5 py-3 text-sm font-semibold tracking-tight text-[#ff6b6b] transition hover:bg-[#ff6b6b]/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Processing..." : "Unsubscribe this email"}
            </button>
          </div>
        ) : (isSuccess || isError) ? (
          <div className="mt-6">
            <Link
              href="/"
              className="inline-flex items-center justify-center gap-2 rounded-full border border-white/10 px-5 py-3 text-sm tracking-tight text-white/72 transition hover:border-white/24 hover:text-white"
            >
              Back to Home
            </Link>
          </div>
        ) : null}
      </div>
    </section>
  );
}
