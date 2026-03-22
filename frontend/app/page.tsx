import type { Metadata } from "next";
import Link from "next/link";

import { BitcoinPanel } from "@/components/bitcoin/BitcoinPanel";
import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { QualityBanner } from "@/components/layout/QualityBanner";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { TickerBar } from "@/components/layout/TickerBar";
import { StocksBoard } from "@/components/market/StocksBoard";
import { NewsFeed } from "@/components/news/NewsFeed";
import { XSignals } from "@/components/signals/XSignals";
import { fetchLatest } from "@/lib/r2";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "SOVEREIGN BRIEF는 한국 시간 아침에 핵심 수치와 공식 시그널을 큐레이션해 오늘 장의 판단을 빠르게 돕습니다.",
};

export default async function HomePage() {
  const brief = await fetchLatest();
  const indexItems = brief.marketSnapshot.items.filter((item) =>
    ["US10Y", "DXY", "VIX", "KRW", "NQ1!", "BTC"].includes(item.symbol),
  );
  const usIndices = brief.marketSnapshot.items.filter((item) =>
    ["SPX", "QQQ", "SOXX"].includes(item.symbol),
  );

  return (
    <main className="space-y-10 xl:space-y-14">
      <SiteHeader generatedAt={brief.meta.generatedAt} />
      {indexItems.length >= 3 ? <TickerBar items={indexItems} /> : null}
      {brief.meta.dataQuality !== "ok" ? (
        <QualityBanner quality={brief.meta.dataQuality} notes={brief.meta.qualityNotes} />
      ) : null}
      <section id="brief" className="space-y-8">
        <JudgmentBlock
          headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
          summaryLead={brief.aiJudgment.summaryLead}
          summarySupport={brief.aiJudgment.summarySupport}
          generatedAt={brief.meta.generatedAt}
        />
        <div className="space-y-8">
          <section id="market">
            <StocksBoard indices={usIndices} stocks={brief.techStocks} />
          </section>
          <section id="btc">
            <BitcoinPanel bitcoin={brief.bitcoin} />
          </section>
        </div>
      </section>
      <section className="grid gap-8 2xl:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.88fr)]">
        <div className="space-y-8">
          <TopicGrid items={brief.topicSummaries} />
          <section className="panel rounded-[32px] px-6 py-6 md:px-8">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-2">
                <p className="section-title">오늘의 판단</p>
                <p className="text-base leading-7 text-[var(--text-secondary)] md:text-lg">
                  홈에서는 노이즈를 덜어낸 판단 카드부터 읽고, 전체 발행본은 상세 페이지에서 이어서 확인할 수 있습니다.
                </p>
              </div>
              <Link
                href={`/archive/${brief.meta.date}`}
                className="inline-flex items-center justify-center rounded-full border border-[var(--accent-primary)]/35 bg-[var(--accent-primary)]/10 px-5 py-3 font-mono text-[11px] tracking-[0.18em] text-[var(--accent-primary)] transition hover:bg-[var(--accent-primary)]/18"
              >
                오늘의 판단 열기 →
              </Link>
            </div>
          </section>
          <section id="news">
            <NewsFeed items={brief.featuredNews} limit={5} />
          </section>
        </div>
        <aside className="space-y-8 2xl:sticky 2xl:top-[118px] self-start">
          <XSignals items={brief.featuredXSignals} limit={5} />
        </aside>
      </section>
    </main>
  );
}
