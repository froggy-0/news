import React from "react";
import { ExternalLink } from "lucide-react";

import type { NewsItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { RelativeTime } from "@/components/ui/RelativeTime";
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
    return <DataState title="뉴스 상태" message={emptyMessage} family="reading" minHeight={220} />;
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
      {items.map((item, index) => {
        const displayTitle = item.title?.trim() || item.rawTitle?.trim() || item.url;
        const interpretation =
          filterMeaningless(item.interpretation) || filterMeaningless(item.summaryKo) || null;
        const rawTitle = item.rawTitle ?? (!containsKorean(item.title) ? item.title : null);
        const leadSentences = (item.summaryKo ?? "")
          .split(". ")
          .filter((sentence) => sentence.trim())
          .slice(0, index === 0 ? 3 : 2)
          .map((sentence) => `${sentence.trim()}${sentence.endsWith(".") ? "" : "."}`);

        return (
          <a
            key={item.id}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className={`card-reading card-family-reading group relative flex flex-col overflow-hidden rounded-[var(--card-radius-reading)] p-[var(--card-padding-reading)] ${
              index === 0 ? "md:col-span-2 xl:col-span-2 xl:min-h-[23rem]" : ""
            }`}
          >
            <div className="absolute left-0 top-0 h-px w-full bg-gradient-to-r from-[var(--accent-primary)]/80 via-[var(--accent-primary)]/20 to-transparent" />
            <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-[var(--accent-primary)]/80 via-[var(--accent-primary)]/14 to-transparent" />

            <div className="mb-4 flex items-center gap-3">
              <span className="label-meta text-white/26">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="card-reading-meta label-meta text-white/46 transition-colors group-hover:text-white/78">
                {item.source}
              </span>
              <span className="label-meta text-[var(--accent-primary)]/72">
                {categoryLabel(item.category)}
              </span>
            </div>

            <div className="flex flex-1 flex-col gap-6">
              <h3
                className={`card-reading-title font-bold tracking-tight text-white transition-colors group-hover:text-[var(--accent-primary)] ${
                  index === 0 ? "text-[22px] leading-[1.15] md:text-[28px]" : "text-[18px] leading-tight md:text-[20px]"
                }`}
              >
                {displayTitle}
              </h3>

              {showRawTitle && rawTitle && rawTitle !== displayTitle ? (
                <p className="label-meta normal-case tracking-[0.08em] text-white/30">
                  원문 제목 · {rawTitle}
                </p>
              ) : null}

              {leadSentences.length > 0 ? (
                <div className={`space-y-3 ${index === 0 ? "max-w-2xl" : ""}`}>
                  <span className="label-meta text-white/28">
                    뉴스 해설
                  </span>
                  <div className="space-y-2.5">
                    {leadSentences.map((sentence) => (
                      <p
                        key={sentence}
                        className={`card-reading-copy text-white/82 ${
                          index === 0 ? "text-[15px] leading-8 md:text-[16px]" : "text-[13.5px] leading-7"
                        }`}
                      >
                        {sentence}
                      </p>
                    ))}
                  </div>
                </div>
              ) : null}

              {interpretation ? (
                <div className="border-t border-white/8 pt-4">
                  <span className="label-meta text-white/30">
                    시장 함의
                  </span>
                  <p className="mt-2 text-[12px] leading-6 text-white/68">{interpretation}</p>
                </div>
              ) : null}
            </div>

            <div className="mt-6 flex items-end justify-between border-t border-white/6 pt-5">
              <div className="card-reading-meta label-meta flex flex-wrap items-center gap-x-4 gap-y-2 text-white/38">
                <RelativeTime value={item.publishedAt} />
                <span>{item.sourceTier === "tier1" ? "Tier 1" : "Verified"}</span>
                {item.tags.slice(0, 2).map((tag) => (
                  <span key={tag}>#{tag}</span>
                ))}
              </div>
              <div className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 transition-all group-hover:border-[var(--accent-primary)]/40 group-hover:bg-[var(--accent-primary)]/10">
                <ExternalLink className="h-3.5 w-3.5 text-white/30 transition-colors group-hover:text-[var(--accent-primary)]" />
              </div>
            </div>
          </a>
        );
      })}
    </div>
  );
}
