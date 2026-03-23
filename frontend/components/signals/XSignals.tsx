import type { XSignal } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { Reveal } from "@/components/ui/Reveal";
import { formatRelativeTime } from "@/lib/format";

const HANGUL_RE = /[가-힣]/;

function containsKorean(text: string | null | undefined): boolean {
  return Boolean(text && HANGUL_RE.test(text));
}

function sentimentLabel(value: XSignal["sentiment"]): string {
  if (value === "bullish") {
    return "상방";
  }
  if (value === "bearish") {
    return "하방";
  }
  return "중립";
}

export function XSignals({
  items,
  limit,
  showRawToggle = false,
}: {
  items: XSignal[] | null;
  limit?: number;
  showRawToggle?: boolean;
}) {
  if (!items || items.length === 0) {
    return null;
  }

  const visibleItems = typeof limit === "number" ? items.slice(0, limit) : items;

  return (
    <Reveal className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
      <div className="mb-8 flex flex-col gap-3 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">공식 X 시그널</p>
          <h2 className="display-headline mt-4 max-w-4xl text-[2.1rem] md:text-[3.2rem]">
            공식 채널에서 먼저 나온 문장을 짧게 읽고, 시장 영향만 남깁니다.
          </h2>
        </div>
        <p className="hero-support max-w-sm">
          {typeof limit === "number"
            ? "홈에서는 방향을 바꿀 수 있는 핵심 시그널만 선별해 이어서 읽게 합니다."
            : "상세에서는 전체 시그널을 다시 읽고, 필요하면 원문 표현도 함께 확인할 수 있습니다."}
        </p>
      </div>

      {visibleItems.length === 0 ? (
        <DataState message="이번 집계에서는 공식 X 시그널을 확인하지 못했어요." />
      ) : (
        <div className="divide-y divide-white/8">
          {visibleItems.map((item) => {
            const displayContent = item.content?.trim() || item.rawContent?.trim() || "";
            const displayImpact = item.impact?.trim() || null;
            const rawContent = item.rawContent ?? (!containsKorean(item.content) ? item.content : null);

            return (
              <article key={item.id} className="grid gap-5 py-6 md:grid-cols-[156px_1fr]">
                <div className="space-y-3">
                  <p className="font-mono text-[11px] tracking-[0.22em] text-[var(--accent-primary)] uppercase">
                    {formatRelativeTime(item.postedAt)}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <span className="inline-flex rounded-full border border-white/10 px-3 py-1 font-mono text-[10px] tracking-[0.18em] text-[var(--text-secondary)] uppercase">
                      {sentimentLabel(item.sentiment)}
                    </span>
                  </div>
                </div>
                <div className="space-y-4">
                  <p className="text-lg leading-8 text-[var(--text-primary)] md:text-[1.15rem]">{displayContent}</p>
                  {displayImpact ? (
                    <div className="rounded-[8px] border border-white/8 bg-white/[0.03] px-4 py-4">
                      <p className="section-title">시장 영향</p>
                      <p className="copy-block mt-3">{displayImpact}</p>
                    </div>
                  ) : null}
                  {showRawToggle && rawContent && rawContent !== displayContent ? (
                    <details className="rounded-[8px] border border-white/8 bg-white/[0.02] px-4 py-4">
                      <summary className="cursor-pointer font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)]">
                        영문 원문 보기
                      </summary>
                      <p className="mt-3 text-sm leading-7 text-[var(--text-secondary)]">{rawContent}</p>
                    </details>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Reveal>
  );
}
