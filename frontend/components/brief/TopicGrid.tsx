import type { TopicSummary } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

const HANGUL_RE = /[가-힣]/;
const MACHINE_PAYLOAD_RE = /^\s*[\[{].*[:].*[\]}]\s*$/;

function formatKeyMetric(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const normalized = value.replace("Fear & Greed", "공포탐욕").trim();
  if (!normalized) {
    return null;
  }
  if (MACHINE_PAYLOAD_RE.test(normalized) || normalized.startsWith("{'") || normalized.startsWith('{"')) {
    return null;
  }
  if (!containsKorean(normalized) && /[A-Za-z]/.test(normalized) && normalized.split(/\s+/).length >= 6) {
    return null;
  }
  return normalized;
}

function containsKorean(value: string | null | undefined): boolean {
  return Boolean(value && HANGUL_RE.test(value));
}

function displaySummary(item: TopicSummary): string | null {
  const normalizedLines: string[] = [];

  for (const rawLine of item.summary.replace(/\r\n/g, "\n").split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    if (MACHINE_PAYLOAD_RE.test(line) || line.startsWith("{'") || line.startsWith('{"')) {
      continue;
    }
    if (!containsKorean(line) && /[A-Za-z]/.test(line) && line.split(/\s+/).length >= 7) {
      continue;
    }
    normalizedLines.push(line);
  }

  const normalized = normalizedLines.join(" ");
  return normalized || null;
}

function displayRelatedStocks(value: string[] | null | undefined): string[] {
  if (!value?.length) {
    return [];
  }

  return value
    .map((entry) => entry.trim())
    .filter(Boolean)
    .filter((entry) => !MACHINE_PAYLOAD_RE.test(entry) && !entry.startsWith("{'") && !entry.startsWith('{"'))
    .filter((entry) => !entry.includes(":") || /^[A-Z0-9.\-!]{1,8}$/.test(entry))
    .slice(0, 5);
}

export function TopicGrid({
  items,
  variant = "detail",
}: {
  items: TopicSummary[];
  variant?: "home" | "detail";
}) {
  const visibleItems = items
    .map((item) => ({
      item,
      summary: displaySummary(item),
      keyMetric: formatKeyMetric(item.keyMetric),
      relatedStocks: displayRelatedStocks(item.relatedStocks),
    }))
    .filter((entry) => entry.summary);

  if (variant === "home") {
    const [leadItem, ...otherItems] = visibleItems;

    return (
      <section id="map" className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
        <div className="mb-8 flex flex-col gap-3 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <p className="section-title">브리핑 지도</p>
            <h2 className="display-headline max-w-5xl text-[2.2rem] md:text-[3.35rem]">
              오늘 장을 움직이는 축부터 먼저 읽습니다.
            </h2>
          </div>
          <p className="eyebrow max-w-sm">
            숫자보다 먼저, 왜 오늘 시장이 그렇게 흘렀는지 핵심 축을 요약합니다.
          </p>
        </div>
        {visibleItems.length === 0 ? (
          <DataState message="이번 집계에서는 토픽 요약을 확인하지 못했어요." />
        ) : (
          <div className="space-y-4">
            {leadItem ? (
              <article className="panel-soft rounded-[8px] border border-white/10 bg-white/[0.03] px-5 py-5 md:px-6 md:py-6">
                <p className="section-title">{leadItem.item.label}</p>
                <p className="mt-4 max-w-4xl text-[1.05rem] leading-8 text-[var(--text-primary)] md:text-[1.18rem]">
                  {leadItem.summary}
                </p>
                {leadItem.keyMetric || leadItem.relatedStocks.length > 0 ? (
                  <div className="mt-5 flex flex-wrap items-center gap-3">
                    {leadItem.keyMetric ? (
                      <p className="numeric font-mono text-[10px] tracking-[0.18em] text-[var(--accent-primary)] uppercase">
                        {leadItem.keyMetric}
                      </p>
                    ) : null}
                    {leadItem.relatedStocks.length > 0 ? (
                      <p className="font-mono text-[10px] tracking-[0.16em] text-[var(--text-muted)] uppercase">
                        {leadItem.relatedStocks.join(" · ")}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </article>
            ) : null}
            {otherItems.length > 0 ? (
              <div className="grid gap-4 md:grid-cols-3">
                {otherItems.map(({ item, summary, keyMetric, relatedStocks }) => (
                  <article key={item.topic} className="panel-soft rounded-[8px] border border-white/8 bg-black/20 px-5 py-5">
                    <p className="section-title">{item.label}</p>
                    <p className="mt-4 text-sm leading-7 text-[var(--text-secondary)]">{summary}</p>
                    {keyMetric ? (
                      <p className="numeric mt-5 font-mono text-[10px] tracking-[0.18em] text-[var(--accent-primary)] uppercase">
                        {keyMetric}
                      </p>
                    ) : null}
                    {relatedStocks.length > 0 ? (
                      <p className="mt-3 font-mono text-[10px] tracking-[0.16em] text-[var(--text-muted)] uppercase">
                        {relatedStocks.join(" · ")}
                      </p>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-7 flex flex-col gap-3 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">브리핑 지도</p>
          <h2 className="display-headline mt-4 text-[2.15rem] md:text-[3.2rem]">오늘 브리핑을 움직이는 축을 먼저 잡습니다.</h2>
        </div>
        <p className="hero-support max-w-sm">거시, 미국 증시, 빅테크, 비트코인 흐름을 먼저 압축해 읽는 상단 맵입니다.</p>
      </div>
      {visibleItems.length === 0 ? (
        <DataState message="이번 집계에서는 토픽 요약을 확인하지 못했어요." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {visibleItems.map(({ item, summary, keyMetric, relatedStocks }) => {
            return (
              <article key={item.topic} className="panel-soft rounded-[26px] px-5 py-5">
                <p className="section-title">{item.label}</p>
                <p className="mt-4 text-base leading-8 text-[var(--text-primary)]">{summary}</p>
                {keyMetric ? (
                  <p className="numeric mt-5 text-sm tracking-[0.18em] text-[var(--accent-primary)] uppercase">{keyMetric}</p>
                ) : null}
                {relatedStocks.length > 0 ? (
                  <p className="mt-4 font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)] uppercase">
                    {relatedStocks.join(" · ")}
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
