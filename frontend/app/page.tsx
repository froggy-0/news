import type { Metadata } from "next";
import Link from "next/link";

import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { QualityBanner } from "@/components/layout/QualityBanner";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { NewsFeed } from "@/components/news/NewsFeed";
import { XSignals } from "@/components/signals/XSignals";
import { fetchLatest } from "@/lib/r2";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "SOVEREIGN BRIEF는 흩어진 영문 기사와 공식 시그널을 한국어 판단으로 압축해 오늘 장의 맥락을 빠르게 읽게 합니다.",
};

export default async function HomePage() {
  const brief = await fetchLatest();
  const hasFeaturedNews = brief.featuredNews.length > 0;
  const hasFeaturedSignals = Boolean(brief.featuredXSignals && brief.featuredXSignals.length > 0);

  return (
    <main className="space-y-10 xl:space-y-14">
      <SiteHeader
        generatedAt={brief.meta.generatedAt}
        showNews={hasFeaturedNews}
        showSignals={hasFeaturedSignals}
      />
      {brief.meta.dataQuality !== "ok" ? (
        <QualityBanner quality={brief.meta.dataQuality} notes={brief.meta.qualityNotes} />
      ) : null}
      <section id="brief" className="space-y-8">
        <JudgmentBlock
          headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
          summaryLead={brief.aiJudgment.summaryLead}
          summarySupport={brief.aiJudgment.summarySupport}
          generatedAt={brief.meta.generatedAt}
          variant="home"
        />
      </section>
      <section className="space-y-8">
        <TopicGrid items={brief.topicSummaries} variant="home" />
        {hasFeaturedNews ? (
          <section id="news">
            <NewsFeed items={brief.featuredNews} limit={5} />
          </section>
        ) : null}
        {hasFeaturedSignals ? (
          <section id="signals">
            <XSignals items={brief.featuredXSignals} limit={5} />
          </section>
        ) : null}
        <section className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div className="space-y-2">
              <p className="section-title">전체 발행본</p>
              <h2 className="section-headline max-w-4xl">
                핵심만 먼저 읽고, 전체 발행본으로 이어집니다.
              </h2>
              <p className="copy-block max-w-2xl">
                홈에서는 핵심 판단과 이슈만 먼저 읽고, 상세 페이지에서는 수치 블록과 전체 본문, 전체 뉴스 흐름을 다시 확인할 수 있습니다.
              </p>
            </div>
            <Link
              href={`/archive/${brief.meta.date}`}
              className="inline-flex items-center justify-center rounded-full border border-[var(--accent-primary)]/35 bg-[var(--accent-primary)]/10 px-5 py-3 font-mono text-[11px] tracking-[0.18em] text-[var(--accent-primary)] transition hover:bg-[var(--accent-primary)]/18"
            >
              전체 발행본 보기 →
            </Link>
          </div>
        </section>
      </section>
    </main>
  );
}
