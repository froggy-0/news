import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BriefBody } from "@/components/brief/BriefBody";
import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { RiskOverlayPanel } from "@/components/brief/RiskOverlayPanel";
import { SovereignIndexPanel } from "@/components/brief/SovereignIndexPanel";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { CryptoPulseBoard } from "@/components/market/CryptoPulseBoard";
import { SourceFeed } from "@/components/feed/SourceFeed";
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
    const brief = await fetchBriefByDate(date);

    return (
      <main className="pb-6">
        <SiteHeader variant="archive-detail" />
        <JudgmentBlock
          headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
          summaryLead={brief.aiJudgment.summaryLead}
          summarySupport={brief.aiJudgment.summarySupport}
          issueDate={brief.meta.date}
        />
        <RiskOverlayPanel overlay={brief.riskOverlay} />
        <SovereignIndexPanel sovereignIndex={brief.sovereignIndex} />
        <CryptoPulseBoard
          snapshot={brief.marketSnapshot}
          indicators={brief.cryptoIndicators}
          bitcoin={brief.bitcoin}
          etfHistory={brief.etfHistory}
        />
        <BriefBody body={brief.aiJudgment.body} date={brief.meta.date} />
        <TopicGrid items={brief.topicSummaries} />
        <SourceFeed
          featuredNews={brief.featuredNews}
          allNews={brief.allNews}
          featuredXSignals={brief.featuredXSignals}
          allXSignals={brief.allXSignals}
          showRawTitle
          showRawToggle
        />
      </main>
    );
  } catch {
    notFound();
  }
}
