"use client";

import { useState } from "react";

import { SubscriptionState } from "@/components/ui/SubscriptionState";
import type { RequestSubscriptionPayload, RequestSubscriptionResponse } from "@/lib/subscriptions/contracts";

export function SubscriptionForm() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    setError(null);

    try {
      const response = await fetch("/api/subscriptions/request", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({ email } satisfies RequestSubscriptionPayload),
      });
      const payload = (await response.json()) as RequestSubscriptionResponse;
      if (!response.ok) {
        throw new Error("error" in payload ? payload.error : "구독 신청 중 오류가 발생했습니다.");
      }
      setMessage("message" in payload ? payload.message : "확인 메일을 보냈습니다.");
      setEmail("");
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "구독 신청 중 오류가 발생했습니다.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <p className="section-title">Newsletter</p>
          <h2 className="section-headline max-w-3xl">발행 즉시 메일로 받아보세요.</h2>
          <p className="copy-block max-w-2xl">
            이메일을 남기면 확인 메일을 보냅니다. 메일 안의 링크를 눌러야 다음 발송부터 받아볼 수 있습니다.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="flex w-full max-w-xl flex-col gap-3">
          <label className="eyebrow" htmlFor="newsletter-email">
            이메일 주소
          </label>
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              id="newsletter-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              className="min-h-[48px] flex-1 rounded-full border border-white/12 bg-white/5 px-5 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
              required
            />
            <button
              type="submit"
              disabled={submitting}
              className="min-h-[48px] rounded-full bg-[var(--accent-primary)] px-5 py-3 font-mono text-[11px] tracking-[0.18em] text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "보내는 중" : "구독 신청"}
            </button>
          </div>
          {message ? <SubscriptionState tone="success">{message}</SubscriptionState> : null}
          {error ? <SubscriptionState tone="danger">{error}</SubscriptionState> : null}
        </form>
      </div>
    </section>
  );
}
