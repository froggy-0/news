import type { Metadata } from "next";

import { HomeHero } from "@/components/hero/HomeHero";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { fetchLatest } from "@/lib/r2";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "Structured market intelligence — quantitative signals, news sentiment, and daily briefings for sovereign investors.",
};

export default async function HomePage() {
  const brief = await fetchLatest();
  const heroSeed = brief.meta.date;

  return (
    <main className="pb-6">
      <SiteHeader />
      <HomeHero brief={brief} heroSeed={heroSeed} latestDate={brief.meta.date} />
    </main>
  );
}
