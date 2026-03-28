import type { Metadata } from "next";

import { BitcoinPanel } from "@/components/bitcoin/BitcoinPanel";
import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { HomeHero } from "@/components/hero/HomeHero";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { StocksBoard } from "@/components/market/StocksBoard";
import { NewsFeed } from "@/components/news/NewsFeed";
import { XSignals } from "@/components/signals/XSignals";
import { buildHistoryEntries, buildMetaStatusCards } from "@/lib/history";
import { fetchIndex, fetchLatest } from "@/lib/r2";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "글로벌 마켓 데이터의 정교한 연결, 원본의 무결성으로 완성하는 투자 주권.",
};

export default async function HomePage() {
  const [brief, index] = await Promise.all([fetchLatest(), fetchIndex()]);

  return (
    <main className="pb-6">
      <SiteHeader
        historyEntries={buildHistoryEntries(index.dates, brief.meta.date)}
        statusCards={buildMetaStatusCards(brief.meta)}
        currentDate={brief.meta.date}
      />
      <HomeHero brief={brief} />
      <JudgmentBlock
        headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
        summaryLead={brief.aiJudgment.summaryLead}
        summarySupport={brief.aiJudgment.summarySupport}
        issueDate={brief.meta.date}
        variant="home"
      />
      <StocksBoard snapshot={brief.marketSnapshot} stocks={brief.techStocks} variant="home" />
      <BitcoinPanel bitcoin={brief.bitcoin} variant="home" />
      <TopicGrid items={brief.topicSummaries} variant="home" />
      <NewsFeed featuredItems={brief.featuredNews} allItems={brief.allNews} variant="home" />
      <XSignals featuredItems={brief.featuredXSignals} allItems={brief.allXSignals} variant="home" />
    </main>
  );
}
