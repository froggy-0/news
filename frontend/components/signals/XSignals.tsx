import type { XSignal } from "@schema/brief.types";

import { Reveal } from "@/components/ui/Reveal";
import { formatRelativeTime } from "@/lib/format";

function sentimentLabel(value: XSignal["sentiment"]): string {
  if (value === "bullish") {
    return "상방";
  }
  if (value === "bearish") {
    return "하방";
  }
  return "중립";
}

export function XSignals({ items }: { items: XSignal[] | null }) {
  if (!items || items.length === 0) {
    return null;
  }

  return (
    <Reveal className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-7 flex flex-col gap-3 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">공식 X 시그널</p>
          <h2 className="display-headline mt-4 max-w-4xl text-[2.1rem] md:text-[3.2rem]">
            공식 X 시그널에서 포착한 시장 언어를 분리해 보여줍니다.
          </h2>
        </div>
        <p className="hero-support max-w-sm">가격보다 먼저 방향을 만든 문장과 그 파급 효과를 따로 읽는 보조 스트림입니다.</p>
      </div>

      <div className="divide-y divide-white/8">
        {items.map((item) => (
          <article key={item.id} className="grid gap-5 py-6 md:grid-cols-[156px_1fr]">
            <div className="space-y-3">
              <p className="font-mono text-[11px] tracking-[0.22em] text-[var(--accent-primary)] uppercase">
                {formatRelativeTime(item.postedAt)}
              </p>
              <span className="inline-flex rounded-full border border-white/10 px-3 py-1 font-mono text-[10px] tracking-[0.18em] text-[var(--text-secondary)] uppercase">
                {sentimentLabel(item.sentiment)}
              </span>
            </div>
            <div className="space-y-4">
              <p className="text-lg leading-8 text-[var(--text-primary)] md:text-xl">{item.content}</p>
              <div className="rounded-[18px] border border-white/8 bg-white/[0.03] px-4 py-4">
                <p className="section-title">시장 영향</p>
                <p className="copy-block mt-3">{item.impact}</p>
              </div>
            </div>
          </article>
        ))}
      </div>
    </Reveal>
  );
}
