import React from "react";
import type { BriefData } from "@schema/brief.types";

import { SubscriptionForm } from "@/components/layout/SubscriptionForm";
import { displayHeadline, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

import { TerminalPanel } from "./TerminalPanel";

export function HomeHero({
  brief,
  heroSeed,
  latestDate,
}: {
  brief: BriefData;
  heroSeed: string;
  latestDate: string;
}) {
  const heroHeadline = hasUsableHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    ? displayHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    : `${formatPublicationDate(brief.meta.date)} Brief`;

  return (
    <section className="hero-stage" data-hero-seed={heroSeed}>
      <div className="relative z-10 mx-auto flex w-full max-w-4xl flex-col items-center px-6 text-center">

        {/* Eyebrow */}
        <p
          className="mb-10 font-mono text-[0.65rem] uppercase tracking-[0.32em]"
          style={{ color: "var(--accent-primary)", opacity: 0.7 }}
        >
          Wall Street · Sovereign Intelligence · {brief.meta.date}
        </p>

        {/* Giant editorial headline */}
        <h1
          className="mb-7 leading-[1.04] tracking-[-0.05em]"
          style={{
            fontFamily: "var(--font-instrument-serif), serif",
            fontStyle: "italic",
            fontSize: "clamp(3rem, 7.5vw, 6rem)",
          }}
        >
          <span className="block text-[var(--text-primary)]">Sovereign Market</span>
          <span className="block" style={{ color: "var(--accent-primary)" }}>
            Intelligence.
          </span>
        </h1>

        {/* Subheadline */}
        <p className="mb-10 max-w-2xl text-[1.05rem] leading-7 text-white/50">
          Structured market data, news sentiment, and quantitative signals unified
          into a single daily intelligence brief — before the narrative forms.
        </p>

        {/* Subscription form — centered, full-width */}
        <div id="subscribe" className="mb-12 w-full max-w-md">
          <SubscriptionForm />
        </div>

        {/* Today's signal card */}
        <div
          className="w-full max-w-2xl overflow-hidden rounded-2xl border p-6 text-left"
          style={{
            borderColor: "rgba(255,220,140,0.12)",
            background: "linear-gradient(145deg, rgba(255,248,235,0.045), rgba(255,248,235,0.012))",
            backdropFilter: "blur(16px)",
          }}
        >
          <p
            className="mb-3 font-mono text-[0.62rem] uppercase tracking-[0.22em]"
            style={{ color: "var(--accent-primary)", opacity: 0.65 }}
          >
            Today&apos;s Signal · {brief.meta.date}
          </p>
          <p className="mb-5 text-[1rem] leading-7 text-white/82">{heroHeadline}</p>
          <a
            href={`/archive/${latestDate}`}
            className="hero-cta-primary inline-flex rounded-[14px] px-6 py-3 text-[14px]"
            style={{ minHeight: "auto" }}
          >
            Read Today&apos;s Brief
          </a>
        </div>

        {/* Terminal status strip */}
        <div className="mt-8 w-full max-w-2xl">
          <TerminalPanel meta={brief.meta} compact />
        </div>
      </div>
    </section>
  );
}
