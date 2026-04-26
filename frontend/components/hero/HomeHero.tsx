import React from "react";
import type { BriefData } from "@schema/brief.types";

import { SubscriptionForm } from "@/components/layout/SubscriptionForm";
import { displayHeadline, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

import { ScatterText } from "./ScatterText";
import { TerminalPanel } from "./TerminalPanel";

export function HomeHero({ brief, heroSeed, latestDate }: { brief: BriefData; heroSeed: string; latestDate: string }) {
  const heroHeadline = hasUsableHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    ? displayHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    : `${formatPublicationDate(brief.meta.date)} Brief`;

  return (
    <section className="hero-stage" data-hero-seed={heroSeed}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 sm:px-6">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.08fr)_minmax(20rem,0.92fr)] lg:items-end">
          <div className="space-y-5">
            <div className="space-y-3">
              <p className="eyebrow">Daily Intelligence Brief</p>
              <h1 className="max-w-[12ch] text-[2.2rem] font-black leading-[1.04] tracking-[-0.07em] text-[var(--text-primary)] md:text-[3.8rem]">
                <span>Sovereign</span>
                <br />
                <span>Market</span>
                <br />
                <ScatterText
                  text="Intelligence"
                  seed={heroSeed}
                  fontSize={58}
                  density={0.72}
                  spread={0.28}
                  durationMs={920}
                />
              </h1>
              <p className="copy-block max-w-[36rem] text-[1rem] text-[var(--text-secondary)]">
                Structured market data, news sentiment, and quantitative signals
                <br className="hidden sm:block" />
                unified into a single daily intelligence brief.
              </p>
            </div>

            <div className="card-family-reading space-y-4 rounded-[var(--card-radius-reading)] p-[var(--card-padding-reading)]">
              <div className="space-y-2">
                <p className="section-title">Today&apos;s Signal</p>
                <p className="max-w-[34rem] text-[1.05rem] leading-7 text-[var(--text-primary)] md:text-[1.1rem]">
                  {heroHeadline}
                </p>
                <p className="text-[0.88rem] leading-6 text-[var(--text-secondary)]">
                  Reference date {brief.meta.date} — read the latest brief above the fold.
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                <a href={`/archive/${latestDate}`} className="hero-cta-primary">
                  Read Today&apos;s Brief
                </a>
              </div>
            </div>
          </div>

          <div className="space-y-4 lg:pb-1">
            <div id="subscribe" className="card-family-utility rounded-[var(--card-radius-utility)] p-[var(--card-padding-utility)]">
              <div className="mb-4 space-y-2">
                <p className="section-title">Brief Access</p>
                <p className="text-[0.94rem] leading-6 text-[var(--text-secondary)]">
                  Subscribe free — receive the same structured brief by email every morning.
                </p>
              </div>
              <SubscriptionForm />
            </div>
          </div>
        </div>

        <div className="pt-1">
          <TerminalPanel meta={brief.meta} compact />
        </div>
      </div>
    </section>
  );
}
