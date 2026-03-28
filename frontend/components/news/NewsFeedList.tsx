import React from "react";
import { ExternalLink, ShieldCheck, Sparkles, Zap } from "lucide-react";

import type { NewsItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { formatRelativeTime } from "@/lib/format";
import { containsKorean, filterMeaningless } from "@/lib/text";

function categoryLabel(value: NewsItem["category"]): string {
  if (value === "macro") return "거시";
  if (value === "bigtech") return "빅테크";
  if (value === "bitcoin") return "비트코인";
  return "미국 증시";
}

export function NewsFeedList({
  items,
  showRawTitle = false,
  emptyMessage,
}: {
  items: NewsItem[];
  showRawTitle?: boolean;
  emptyMessage: string;
}) {
  if (items.length === 0) {
    return <DataState message={emptyMessage} />;
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
      {items.map((item) => {
        const displayTitle = item.title?.trim() || item.rawTitle?.trim() || item.url;
        const interpretation =
          filterMeaningless(item.interpretation) || filterMeaningless(item.summaryKo) || null;
        const rawTitle = item.rawTitle ?? (!containsKorean(item.title) ? item.title : null);

        return (
          <a
            key={item.id}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="group relative flex flex-col overflow-hidden rounded-[22px] border border-white/8 bg-[#0a0a0a] p-6 transition-all duration-500 hover:border-[#00ffff]/30 hover:bg-white/[0.03]"
          >
            <div className="mb-5 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`h-2 w-2 rounded-full ${
                    item.urgency === "high"
                      ? "bg-[#ff6b6b] shadow-[0_0_8px_rgba(255,107,107,0.5)]"
                      : item.urgency === "medium"
                        ? "bg-[#00ffff] shadow-[0_0_8px_rgba(0,255,255,0.35)]"
                        : "bg-white/20"
                  }`}
                />
                <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-white/42 transition-colors group-hover:text-white/82">
                  {item.source}
                </span>
              </div>
              <div className="flex items-center gap-2 rounded border border-white/10 bg-white/[0.03] px-2 py-1">
                <ShieldCheck className="h-3 w-3 text-[#00ffff]" />
                <span className="text-[8px] font-mono uppercase tracking-[0.16em] text-white/48">
                  {item.sourceTier === "tier1" ? "TIER 1" : "VERIFIED"}
                </span>
              </div>
            </div>

            <div className="flex flex-1 flex-col gap-5">
              <h3 className="text-[17px] font-bold leading-tight tracking-tight text-white transition-colors group-hover:text-[#00ffff] md:text-[19px]">
                {displayTitle}
              </h3>

              {showRawTitle && rawTitle && rawTitle !== displayTitle ? (
                <p className="text-[10px] font-mono tracking-[0.16em] text-white/34">
                  원문 제목 · {rawTitle}
                </p>
              ) : null}

              {item.summaryKo ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="h-px flex-1 bg-white/10" />
                    <span className="text-[9px] font-mono uppercase tracking-[0.28em] text-white/28">
                      핵심 인사이트
                    </span>
                    <div className="h-px flex-1 bg-white/10" />
                  </div>
                  <ul className="space-y-2">
                    {item.summaryKo
                      .split(". ")
                      .filter((sentence) => sentence.trim())
                      .slice(0, 2)
                      .map((sentence) => (
                        <li key={sentence} className="flex gap-2 text-[12px] leading-6 text-white/60">
                          <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[#00ffff]/70" />
                          <span>{sentence.trim()}{sentence.endsWith(".") ? "" : "."}</span>
                        </li>
                      ))}
                  </ul>
                </div>
              ) : null}

              {interpretation ? (
                <div className="rounded-r-md border-l-2 border-[#00ffff]/40 bg-white/[0.02] p-4">
                  <div className="mb-2 flex items-center gap-1.5">
                    <Zap className="h-3 w-3 text-[#00ffff]" />
                    <span className="text-[9px] font-mono uppercase tracking-[0.22em] text-white/46">
                      AI 전략적 영향
                    </span>
                  </div>
                  <p className="text-[12px] leading-6 text-white/78">{interpretation}</p>
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2">
                {item.tags.slice(0, 3).map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1 text-[9px] font-mono uppercase tracking-[0.14em] text-white/36"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-6 flex items-end justify-between border-t border-white/6 pt-5">
              <div className="flex items-center gap-5">
                <div className="flex flex-col gap-1">
                  <span className="text-[8px] font-mono uppercase tracking-[0.18em] text-white/26">
                    발행 시각
                  </span>
                  <span className="text-[10px] font-mono text-white/58">{formatRelativeTime(item.publishedAt)}</span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[8px] font-mono uppercase tracking-[0.18em] text-white/26">
                    카테고리
                  </span>
                  <span className="text-[10px] font-mono uppercase text-[#00ffff]">
                    {categoryLabel(item.category)}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-white/12 transition-colors group-hover:text-[#00ffff]/60" />
                <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 transition-all group-hover:border-[#00ffff]/40 group-hover:bg-[#00ffff]/10">
                  <ExternalLink className="h-3 w-3 text-white/30 transition-colors group-hover:text-[#00ffff]" />
                </div>
              </div>
            </div>
          </a>
        );
      })}
    </div>
  );
}
