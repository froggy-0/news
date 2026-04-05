import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BitcoinPanel } from "@/components/bitcoin/BitcoinPanel";
import { BriefBody } from "@/components/brief/BriefBody";
import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { StocksBoard } from "@/components/market/StocksBoard";
import { NewsFeed } from "@/components/news/NewsFeed";
import { XSignals } from "@/components/signals/XSignals";
import { buildHistoryEntries } from "@/lib/history";
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
    description: brief.meta.displayHeadline || brief.aiJudgment.headline,
  };
}

export default async function ArchiveDetailPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;

  try {
    const [brief, index] = await Promise.all([fetchBriefByDate(date), fetchIndex()]);

    return (
      <main className="pb-6">
        <SiteHeader
          variant="archive-detail"
          historyEntries={buildHistoryEntries(index.dates, brief.meta.date)}
          currentDate={brief.meta.date}
        />
        <JudgmentBlock
          headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
          summaryLead={brief.aiJudgment.summaryLead}
          summarySupport={brief.aiJudgment.summarySupport}
          issueDate={brief.meta.date}
        />
        <StocksBoard snapshot={brief.marketSnapshot} stocks={brief.techStocks} />
        <BitcoinPanel bitcoin={brief.bitcoin} />
        <BriefBody body={brief.aiJudgment.body} date={brief.meta.date} />
        <TopicGrid items={brief.topicSummaries} />
        <NewsFeed
          featuredItems={brief.featuredNews}
          allItems={brief.allNews}
          showRawTitle
        />
        <XSignals
          featuredItems={brief.featuredXSignals}
          allItems={brief.allXSignals}
          showRawToggle
        />
      </main>
    );
  } catch {
    notFound();
  }
}
