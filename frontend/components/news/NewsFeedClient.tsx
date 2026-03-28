import { Sparkles } from "lucide-react";

import type { NewsItem } from "@schema/brief.types";

import { NewsFeedList } from "./NewsFeedList";

export function NewsFeedClient({
  featuredItems,
  allItems,
}: {
  featuredItems: NewsItem[];
  allItems: NewsItem[];
}) {
  const items = featuredItems.length > 0 ? featuredItems : allItems;

  return (
    <section id="news" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-[#00ffff]/10 p-2.5">
              <Sparkles className="h-4 w-4 text-[#00ffff]" />
            </div>
            <div className="flex max-w-xl flex-col gap-1">
              <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">
                AI 뉴스 분석
              </h2>
              <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
                AI-Synthesized Insights
              </span>
              <p className="pt-2 text-[15px] leading-7 text-white/66">
                오늘 꼭 읽어야 할 기사들을 짧은 해설과 함께 다시 편집해 보여줍니다.
              </p>
            </div>
          </div>
        </div>

        <NewsFeedList
          items={items}
          emptyMessage="이번 집계에서는 주요 뉴스를 확인하지 못했어요."
        />
      </div>
    </section>
  );
}
