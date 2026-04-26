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
          placeholder="Enter your email"
          className="h-14 w-full rounded-[20px] border border-[rgba(255,220,140,0.14)] bg-[#0b0906]/70 px-4 pr-11 text-[15px] tracking-tight text-white outline-none transition placeholder:text-white/28 focus:border-[var(--accent-primary)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--accent-primary)_28%,transparent)]"
          required
        />
        <Mail className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/20 transition group-focus-within:text-[var(--accent-primary)]" />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="group flex h-14 w-full items-center justify-center gap-2 rounded-[20px] bg-[var(--accent-primary)] px-4 text-[15px] font-bold tracking-tight text-[#0b0906] transition hover:bg-[#e8a820] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Processing...
          </>
        ) : (
          <>
            Subscribe Free
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </>
        )}
      </button>
      <p className="text-[13px] leading-6 text-white/38">
        Confirm via email link — you&apos;ll receive the next brief after verification.
      </p>
      {message ? <SubscriptionState tone="success">{message}</SubscriptionState> : null}
      {error ? <SubscriptionState tone="danger">{error}</SubscriptionState> : null}
    </form>
  );
}
