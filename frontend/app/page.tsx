import type { Metadata } from "next";

import { HomeHero } from "@/components/hero/HomeHero";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { buildHistoryEntries } from "@/lib/history";
import { fetchIndex, fetchLatest } from "@/lib/r2";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "Structured market intelligence — quantitative signals, news sentiment, and daily briefings for sovereign investors.",
};

export default async function HomePage() {
  const [brief, index] = await Promise.all([fetchLatest(), fetchIndex()]);
  const heroSeed = brief.meta.date;

  return (
    <main className="pb-6">
      <SiteHeader
        historyEntries={buildHistoryEntries(index.dates, brief.meta.date)}
        currentDate={brief.meta.date}
      />
      <HomeHero brief={brief} heroSeed={heroSeed} latestDate={brief.meta.date} />
    </main>
  );
}
