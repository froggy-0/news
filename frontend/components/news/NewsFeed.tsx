import type { NewsItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { Reveal } from "@/components/ui/Reveal";
import { formatRelativeTime } from "@/lib/format";

const HANGUL_RE = /[가-힣]/;

function containsKorean(text: string | null | undefined): boolean {
  return Boolean(text && HANGUL_RE.test(text));
}

function urgencyLabel(value: NewsItem["urgency"]): string {
  if (value === "high") {
    return "높음";
  }
  if (value === "medium") {
    return "보통";
  }
  return "낮음";
}

function categoryLabel(value: NewsItem["category"]): string {
  if (value === "macro") return "거시";
  if (value === "bigtech") return "빅테크";
  if (value === "bitcoin") return "비트코인";
  return "미국 증시";
}

export function NewsFeed({
  items,
  limit,
  showRawTitle = false,
}: {
  items: NewsItem[];
  limit?: number;
  showRawTitle?: boolean;
}) {
  const visibleItems = typeof limit === "number" ? items.slice(0, limit) : items;

  return (
    <Reveal className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
      <div className="mb-8 flex flex-col gap-3 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-[var(--accent-primary)]" />
            <p className="section-title">핵심 뉴스</p>
          </div>
          <h3 className="serif-display text-[2.2rem] italic tracking-[-0.04em] text-[var(--text-primary)] md:text-[3.2rem]">
            {typeof limit === "number" ? "오늘의 뉴스 5건" : "전체 뉴스 플로우"}
          </h3>
        </div>
        <p className="eyebrow">
          {typeof limit === "number"
            ? "홈에서는 핵심 흐름만 먼저 읽을 수 있게 요약해 보여줍니다"
            : "상세에서는 원문 링크와 함께 전체 뉴스를 다시 확인할 수 있습니다"}
        </p>
      </div>
      {visibleItems.length === 0 ? (
        <DataState message="이번 집계에서는 주요 뉴스를 확인하지 못했어요." />
      ) : (
        <div className="divide-y divide-white/8">
          {visibleItems.map((item) => {
            const displayTitle = item.title?.trim() || item.rawTitle?.trim() || item.url;
            const interpretation = item.interpretation?.trim() || item.summaryKo?.trim() || null;
            const rawTitle = item.rawTitle ?? (!containsKorean(item.title) ? item.title : null);

            return (
              <article key={item.id} className="news-card-glass group relative overflow-hidden px-1 py-8 md:px-3 md:py-10">
                <div className="news-card-glow" aria-hidden="true" />
                <div className="flex flex-col gap-6 md:flex-row md:gap-10">
                  <div className="md:w-32 md:shrink-0">
                    <div className="flex flex-wrap items-center gap-2 md:flex-col md:items-start">
                      <span className="font-mono text-sm font-semibold text-[var(--accent-primary)]">
                        {formatRelativeTime(item.publishedAt)}
                      </span>
                      <span
                        className={`rounded-[4px] px-2 py-1 font-mono text-[9px] tracking-[0.18em] ${
                          item.urgency === "high"
                            ? "bg-red-500/20 text-[var(--accent-down)]"
                            : item.urgency === "medium"
                              ? "bg-[var(--accent-primary)]/12 text-[var(--accent-primary)]"
                              : "bg-white/6 text-[var(--text-secondary)]"
                        }`}
                      >
                        {urgencyLabel(item.urgency)}
                      </span>
                      <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--text-muted)]">
                        {categoryLabel(item.category)}
                      </span>
                    </div>
                  </div>

                  <div className="flex-1 space-y-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="font-mono text-[10px] tracking-[0.24em] text-[var(--accent-cyan)]">
                        {item.source}
                      </span>
                      {item.sourceTier === "tier1" ? (
                        <span className="rounded-[4px] border border-[var(--accent-gold)]/35 px-2 py-1 font-mono text-[9px] tracking-[0.18em] text-[var(--accent-gold)]">
                          핵심 출처
                        </span>
                      ) : null}
                    </div>

                    <a href={item.url} target="_blank" rel="noreferrer" className="block">
                      <h4 className="serif-display text-[1.85rem] leading-[1.18] tracking-[-0.03em] text-[var(--text-primary)] transition-colors group-hover:text-[var(--accent-primary)] md:text-[2.65rem]">
                        {displayTitle}
                      </h4>
                    </a>

                    {showRawTitle && rawTitle && rawTitle !== displayTitle ? (
                      <p className="font-mono text-[10px] tracking-[0.16em] text-[var(--text-muted)]">
                        원문 제목 · {rawTitle}
                      </p>
                    ) : null}

                    {interpretation ? (
                      <div className="border-l-2 border-[var(--accent-primary)]/30 bg-[var(--accent-primary)]/6 px-4 py-3">
                        <p className="font-mono text-[9px] tracking-[0.18em] text-[var(--accent-primary)]">
                          시장 해석
                        </p>
                        <p className="mt-2 text-sm leading-7 text-[var(--text-secondary)]">{interpretation}</p>
                      </div>
                    ) : null}

                    <div className="flex flex-wrap gap-2">
                      {item.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-[999px] border border-white/8 px-3 py-1 font-mono text-[9px] tracking-[0.16em] text-[var(--text-muted)]"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Reveal>
  );
}
