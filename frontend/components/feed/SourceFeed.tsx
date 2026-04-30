import React from "react";

import type { NewsItem, XSignal } from "@schema/brief.types";

import { RevealSection } from "@/components/ui/RevealSection";

import { NewsFeedList } from "../news/NewsFeedList";
import { XSignalsList } from "../signals/XSignalsList";

export function SourceFeed({
  featuredNews,
  allNews,
  featuredXSignals,
  allXSignals,
  showRawTitle = false,
  showRawToggle = false,
}: {
  featuredNews: NewsItem[];
  allNews: NewsItem[];
  featuredXSignals: XSignal[] | null;
  allXSignals: XSignal[] | null;
  showRawTitle?: boolean;
  showRawToggle?: boolean;
}) {
  const hasNews = allNews.length > 0 || featuredNews.length > 0;
  const signals = allXSignals ?? featuredXSignals ?? [];
  const hasSignals = signals.length > 0;

  if (!hasNews && !hasSignals) return null;

  return (
    <RevealSection
      id="sources"
      className="border-b border-white/10 px-6 py-20"
      revealAt={0.9}
      delayMs={40}
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        {/* section header */}
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="section-title">소스 피드</h2>
            <span className="eyebrow">Source Feed</span>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/52">
            오늘 판단의 근거가 된 뉴스와 실시간 시그널을 원문과 함께 확인합니다.
          </p>
        </div>

        {/* news */}
        {hasNews && (
          <div>
            <div className="mb-5 flex items-center gap-3">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent-primary)]" />
              <p className="label-meta text-white/46">뉴스</p>
              <span className="label-meta text-white/24">{allNews.length}건</span>
            </div>
            <NewsFeedList
              items={allNews}
              showRawTitle={showRawTitle}
              emptyMessage="이번 집계에서는 전체 뉴스 흐름을 확인하지 못했어요."
            />
          </div>
        )}

        {/* x signals */}
        {hasSignals && (
          <div>
            <div className="mb-5 flex items-center gap-3">
              <span className="h-1.5 w-1.5 rounded-full bg-white/36" />
              <p className="label-meta text-white/46">X 시그널</p>
              <span className="label-meta text-white/24">{signals.length}건</span>
            </div>
            <XSignalsList
              items={signals}
              showRawToggle={showRawToggle}
              emptyMessage="이번 집계에서는 X 시그널을 확인하지 못했어요."
            />
          </div>
        )}
      </div>
    </RevealSection>
  );
}
