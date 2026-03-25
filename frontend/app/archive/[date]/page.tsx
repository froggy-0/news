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

    const { sourceCounts, translationStatus } = brief.meta;

    return (
      <main className="space-y-8">
        <SiteHeader generatedAt={brief.meta.generatedAt} variant="archive" />
        {brief.meta.dataQuality !== "ok" ? (
          <QualityBanner quality={brief.meta.dataQuality} notes={brief.meta.qualityNotes} />
        ) : null}
        {/* 데이터 수집 현황 및 번역 상태 */}
        <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)] uppercase">
          <span>뉴스 {sourceCounts.newsCandidates}건 수집 → {sourceCounts.newsAll}건 선별</span>
          <span>X 시그널 {sourceCounts.xSignalCandidates}건 수집 → {sourceCounts.xSignalAll}건 선별</span>
          {translationStatus === "partial" ? (
            <span className="text-[var(--accent-gold)]">번역 일부 완료</span>
          ) : translationStatus === "failed" ? (
            <span className="text-[var(--accent-down)]">번역 실패</span>
          ) : null}
        </div>
        <section className="space-y-8">
          <JudgmentBlock
            headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
            summaryLead={brief.aiJudgment.summaryLead}
            summarySupport={brief.aiJudgment.summarySupport}
            generatedAt={brief.meta.generatedAt}
          />
          <StocksBoard indices={usIndices} stocks={brief.techStocks} />
          <BitcoinPanel bitcoin={brief.bitcoin} />
        </section>
        <section className="grid gap-8 2xl:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.88fr)]">
          <div className="space-y-8">
            <BriefBody body={brief.aiJudgment.body} date={brief.meta.date} />
            <TopicGrid items={brief.topicSummaries} />
            <NewsFeed items={brief.allNews} showRawTitle />
          </div>
          <aside className="space-y-8 2xl:sticky 2xl:top-[118px] self-start">
            <XSignals items={brief.allXSignals} showRawToggle />
          </aside>
        </section>
      </main>
    );
  } catch {
    notFound();
  }
}
