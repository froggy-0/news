import React from "react";
import type { NewsItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

import { NewsFeedClient } from "./NewsFeedClient";
import { NewsFeedList } from "./NewsFeedList";

export function NewsFeed({
  featuredItems,
  allItems,
  variant = "home",
  showRawTitle = false,
}: {
  featuredItems: NewsItem[];
  allItems: NewsItem[];
  variant?: "home" | "detail";
  showRawTitle?: boolean;
}) {
  if (featuredItems.length === 0 && allItems.length === 0) {
    return (
      <section id="news" className="border-b border-white/10 px-6 py-16">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="space-y-1">
              <h2 className="section-title">{variant === "home" ? "AI 뉴스 분석" : "전체 뉴스 플로우"}</h2>
              <span className="eyebrow">
                {variant === "home" ? "AI-Synthesized Insights" : "Full Source Flow"}
              </span>
            </div>
          </div>
          <DataState
            title="뉴스 상태"
            message={
              variant === "home"
                ? "이번 집계에서는 주요 뉴스를 확인하지 못했어요."
                : "이번 집계에서는 전체 뉴스 흐름을 확인하지 못했어요."
            }
            family="reading"
            minHeight={220}
          />
        </div>
      </section>
    );
  }

  if (variant === "home") {
    return <NewsFeedClient featuredItems={featuredItems} allItems={allItems} />;
  }

  return (
    <section id="news" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">전체 뉴스 플로우</h2>
            <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
              Full Source Flow
            </span>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/52">
            상세 페이지에서는 featured만이 아니라 전체 뉴스 흐름을 다시 읽고 원문으로 이동할 수 있습니다.
          </p>
        </div>

        <NewsFeedList
          items={allItems}
          showRawTitle={showRawTitle}
          emptyMessage="이번 집계에서는 전체 뉴스 흐름을 확인하지 못했어요."
        />
      </div>
    </section>
  );
}
