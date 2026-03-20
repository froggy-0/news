import type { Metadata } from "next";

import { BitcoinPanel } from "@/components/bitcoin/BitcoinPanel";
import { BriefBody } from "@/components/brief/BriefBody";
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
  description: "SOVEREIGN BRIEF는 미국 기술주와 비트코인 핵심 흐름을 한국 시간 아침 기준으로 빠르게 정리합니다.",
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
      <TickerBar items={indexItems} />
      {brief.meta.dataQuality !== "ok" ? (
        <QualityBanner quality={brief.meta.dataQuality} notes={brief.meta.qualityNotes} />
      ) : null}
      <section id="brief" className="space-y-8">
        <JudgmentBlock
          headline={brief.aiJudgment.headline}
          body={brief.aiJudgment.body}
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
          <BriefBody body={brief.aiJudgment.body} date={brief.meta.date} />
          <TopicGrid items={brief.topicSummaries} />
          <section id="news">
            <NewsFeed items={brief.news} />
          </section>
        </div>
        <aside className="space-y-8 2xl:sticky 2xl:top-[118px] self-start">
          <XSignals items={brief.xSignals} />
        </aside>
      </section>
    </main>
  );
}
