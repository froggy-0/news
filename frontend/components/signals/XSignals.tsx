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

function fallbackContent(value: XSignal["sentiment"]): string {
  if (value === "bullish") {
    return "공식 채널에서 상방 해석이 가능한 신규 시그널이 포착됐어요.";
  }
  if (value === "bearish") {
    return "공식 채널에서 하방 압력을 시사하는 신규 시그널이 포착됐어요.";
  }
  return "공식 채널에서 중립 성격의 신규 시그널이 포착됐어요.";
}

function fallbackImpact(value: XSignal["sentiment"]): string {
  if (value === "bullish") {
    return "관련 자산의 투자 심리와 수급 변화를 함께 확인할 필요가 있어요.";
  }
  if (value === "bearish") {
    return "단기 변동성과 위험 선호 위축 여부를 함께 봐야 해요.";
  }
  return "즉시 방향성보다 맥락 확인이 우선인 신호예요.";
}

function pendingImpact(): string {
  return "한국어 요약을 준비 중이라 원문 시그널을 먼저 보여줍니다.";
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
    <Reveal className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-7 flex flex-col gap-3 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">공식 X 시그널</p>
          <h2 className="display-headline mt-4 max-w-4xl text-[2.1rem] md:text-[3.2rem]">
            공식 채널에서 먼저 나온 문장을 한국어 중심으로 정리해 보여줍니다.
          </h2>
        </div>
        <p className="hero-support max-w-sm">
          {typeof limit === "number"
            ? "홈에서는 방향을 바꿀 수 있는 핵심 시그널만 추려서 보여줍니다."
            : "상세에서는 전체 시그널을 다시 읽고, 필요하면 원문 표현도 함께 확인할 수 있습니다."}
        </p>
      </div>

      {visibleItems.length === 0 ? (
        <DataState message="이번 집계에서는 공식 X 시그널을 확인하지 못했어요." />
      ) : (
        <div className="divide-y divide-white/8">
          {visibleItems.map((item) => {
            const usesRawContent = !containsKorean(item.content) && Boolean(item.content?.trim());
            const displayContent = containsKorean(item.content)
              ? item.content
              : fallbackContent(item.sentiment);
            const displayImpact = containsKorean(item.impact)
              ? item.impact
              : usesRawContent && item.impact?.trim()
                ? pendingImpact()
                : fallbackImpact(item.sentiment);
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
                    {usesRawContent ? (
                      <span className="inline-flex rounded-full border border-white/10 px-3 py-1 font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)] uppercase">
                        번역 대기
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="space-y-4">
                  <p className="text-lg leading-8 text-[var(--text-primary)] md:text-xl">{displayContent}</p>
                  <div className="rounded-[18px] border border-white/8 bg-white/[0.03] px-4 py-4">
                    <p className="section-title">시장 영향</p>
                    <p className="copy-block mt-3">{displayImpact}</p>
                  </div>
                  {showRawToggle && rawContent ? (
                    <details className="rounded-[18px] border border-white/8 bg-white/[0.02] px-4 py-4">
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
