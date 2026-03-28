"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react";

import type { NewsItem } from "@schema/brief.types";

import { NewsFeedList } from "./NewsFeedList";

export function NewsFeedClient({
  featuredItems,
  allItems,
}: {
  featuredItems: NewsItem[];
  allItems: NewsItem[];
}) {
  const [showAll, setShowAll] = useState(featuredItems.length === 0);

  return (
    <section id="news" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-[#00ffff]/10 p-2">
              <Sparkles className="h-4 w-4 text-[#00ffff]" />
            </div>
            <div className="flex flex-col">
              <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">
                AI 뉴스 분석
              </h2>
              <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
                AI-Synthesized Insights
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAll((value) => !value)}
            className="flex items-center gap-2 rounded-full border border-white/10 px-3 py-2 text-[10px] font-mono uppercase tracking-[0.22em] text-white/48 transition hover:border-white/24 hover:text-white"
          >
            {showAll ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            <span>{showAll ? "추천 뉴스" : "전체 인덱스"}</span>
          </button>
        </div>

        <NewsFeedList
          items={showAll ? allItems : featuredItems}
          emptyMessage="이번 집계에서는 주요 뉴스를 확인하지 못했어요."
        />
      </div>
    </section>
  );
}
