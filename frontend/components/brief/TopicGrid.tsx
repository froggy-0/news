import type { TopicSummary } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

function formatKeyMetric(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  return value.replace("Fear & Greed", "공포탐욕");
}

export function TopicGrid({ items }: { items: TopicSummary[] }) {
  return (
    <section className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-7 flex flex-col gap-3 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">브리핑 지도</p>
          <h2 className="display-headline mt-4 text-3xl md:text-5xl">오늘 브리핑을 움직이는 축을 먼저 잡습니다.</h2>
        </div>
        <p className="hero-support max-w-sm">거시, 미국 증시, 빅테크, 비트코인 흐름을 먼저 압축해 읽는 상단 맵입니다.</p>
      </div>
      {items.length === 0 ? (
        <DataState message="이번 집계에서는 토픽 요약을 확인하지 못했어요." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {items.map((item) => (
            <article key={item.topic} className="panel-soft rounded-[26px] px-5 py-5">
              <p className="section-title">{item.label}</p>
              <p className="mt-4 text-base leading-8 text-[var(--text-primary)]">{item.summary}</p>
              {formatKeyMetric(item.keyMetric) ? (
                <p className="numeric mt-5 text-sm tracking-[0.18em] text-[var(--accent-primary)] uppercase">
                  {formatKeyMetric(item.keyMetric)}
                </p>
              ) : null}
              {item.relatedStocks?.length ? (
                <p className="mt-4 font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)] uppercase">
                  {item.relatedStocks.join(" · ")}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
