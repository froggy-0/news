import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BitcoinPanel } from "@/components/bitcoin/BitcoinPanel";
import { BriefBody } from "@/components/brief/BriefBody";
import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { QualityBanner } from "@/components/layout/QualityBanner";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { StocksBoard } from "@/components/market/StocksBoard";
import { NewsFeed } from "@/components/news/NewsFeed";
import { XSignals } from "@/components/signals/XSignals";
import { fetchBriefByDate, fetchIndex } from "@/lib/r2";

export async function generateStaticParams() {
  const index = await fetchIndex();
  return index.dates.map((date) => ({ date }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ date: string }>;
}): Promise<Metadata> {
  const { date } = await params;
  const brief = await fetchBriefByDate(date);
  return {
    title: `${date} · SOVEREIGN BRIEF`,
    description: brief.aiJudgment.headline,
  };
}

export default async function ArchiveDetailPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;
  try {
    const brief = await fetchBriefByDate(date);
    const usIndices = brief.marketSnapshot.items.filter((item) =>
      ["SPX", "QQQ", "SOXX"].includes(item.symbol),
    );

    return (
      <main className="space-y-8">
        <SiteHeader generatedAt={brief.meta.generatedAt} variant="archive" />
        {brief.meta.dataQuality !== "ok" ? (
          <QualityBanner quality={brief.meta.dataQuality} notes={brief.meta.qualityNotes} />
        ) : null}
        <section className="space-y-8">
          <JudgmentBlock
            headline={brief.aiJudgment.headline}
            body={brief.aiJudgment.body}
            generatedAt={brief.meta.generatedAt}
          />
          <StocksBoard indices={usIndices} stocks={brief.techStocks} />
          <BitcoinPanel bitcoin={brief.bitcoin} />
        </section>
        <section className="grid gap-8 2xl:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.88fr)]">
          <div className="space-y-8">
            <BriefBody body={brief.aiJudgment.body} date={brief.meta.date} />
            <TopicGrid items={brief.topicSummaries} />
            <NewsFeed items={brief.news} />
          </div>
          <aside className="space-y-8 2xl:sticky 2xl:top-[118px] self-start">
            <XSignals items={brief.xSignals} />
          </aside>
        </section>
      </main>
    );
  } catch {
    notFound();
  }
}
