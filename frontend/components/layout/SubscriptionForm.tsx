"use client";

import React, { useState } from "react";
import { ArrowRight, Loader2, Mail } from "lucide-react";

import { SubscriptionState } from "@/components/ui/SubscriptionState";
import type {
  RequestSubscriptionPayload,
  RequestSubscriptionResponse,
} from "@/lib/subscriptions/contracts";

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
        throw new Error("error" in payload ? payload.error : "An error occurred. Please try again.");
      }
      setMessage("message" in payload ? payload.message : "Check your inbox for a confirmation link.");
      setEmail("");
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "An error occurred. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="relative group">
        <label className="sr-only" htmlFor="newsletter-email">
          Email address
        </label>
        <input
          id="newsletter-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="이메일을 입력하세요"
          className="h-[52px] w-full rounded-md border border-white/10 bg-white/[0.04] px-5 pr-11 text-[15px] text-[var(--smoke)] outline-none transition-all placeholder:text-white/28 focus:border-[rgba(240,185,11,0.36)] focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(240,185,11,0.08)]"
          required
        />
        <Mail className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--taupe)]/40 transition group-focus-within:text-[var(--taupe)]" />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="group flex h-[52px] w-full cursor-pointer items-center justify-center gap-2 rounded-md px-8 text-[15px] font-semibold text-[#0a0c0e] transition-all hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          background: "linear-gradient(135deg, #f5c430 0%, #e8a800 100%)",
          boxShadow: "0 4px 20px rgba(240,185,11,0.22), inset 0 1px 0 rgba(255,255,255,0.14)",
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 6px 28px rgba(240,185,11,0.34), inset 0 1px 0 rgba(255,255,255,0.20)"; }}
        onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 4px 20px rgba(240,185,11,0.22), inset 0 1px 0 rgba(255,255,255,0.14)"; }}
      >
        {submitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Processing...
          </>
        ) : (
          <>
            무료 구독
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </>
        )}
      </button>
      <p className="font-mono text-[11px] uppercase tracking-[0.10em] text-white/28">
        이메일 확인 후 다음 브리프부터 수신
      </p>
      {message ? <SubscriptionState tone="success">{message}</SubscriptionState> : null}
      {error ? <SubscriptionState tone="danger">{error}</SubscriptionState> : null}
    </form>
  );
}
