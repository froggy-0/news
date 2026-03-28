import React from "react";
import { Activity, Coins, Cpu, Globe, TrendingUp } from "lucide-react";

import type { TopicSummary } from "@schema/brief.types";

const HANGUL_RE = /[가-힣]/;
const MACHINE_PAYLOAD_RE = /^\s*[\[{].*[:].*[\]}]\s*$/;
const ERROR_PATTERNS = /\b(UNABLE|NOT ACCESSIBLE|CANNOT PROVIDE|NO DATA AVAILABLE|DATA NOT|IDENTIFY DATA)\b/i;

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
    if (!containsKorean(line) && /[A-Za-z]/.test(line) && line.split(/\s+/).length >= 5) {
      continue;
    }
    if (ERROR_PATTERNS.test(line)) {
      continue;
    }
    normalizedLines.push(line);
  }

  const normalized = normalizedLines.join(" ");
  return normalized || null;
}

function formatKeyMetric(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.replace("Fear & Greed", "공포탐욕").trim();
  if (!normalized || MACHINE_PAYLOAD_RE.test(normalized) || normalized.startsWith("{'") || normalized.startsWith('{"')) {
    return null;
  }
  if (!containsKorean(normalized) && /[A-Za-z]/.test(normalized) && normalized.split(/\s+/).length >= 6) {
    return null;
  }
  return normalized;
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

function themeIcon(topic: TopicSummary["topic"]) {
  if (topic === "macro") return <Globe className="h-4 w-4" />;
  if (topic === "us-stocks") return <TrendingUp className="h-4 w-4" />;
  if (topic === "bigtech") return <Cpu className="h-4 w-4" />;
  if (topic === "bitcoin") return <Coins className="h-4 w-4" />;
  return <Activity className="h-4 w-4" />;
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

  if (visibleItems.length === 0) {
    return null;
  }

  return (
    <section id="map" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="flex flex-col gap-1">
            <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">오늘의 주요 테마</h2>
            <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
              Contextual Analysis
            </span>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/52">
            숫자와 기사보다 먼저, 오늘 장을 어떤 축으로 읽어야 하는지 해석 레이어를 먼저 제시합니다.
          </p>
        </div>
        <div className={`grid gap-6 ${variant === "home" ? "md:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-2"}`}>
          {visibleItems.map(({ item, summary, keyMetric, relatedStocks }, index) => (
            <article
              key={item.topic}
              className="group relative overflow-hidden rounded-[22px] border border-white/10 bg-white/[0.02] transition-colors duration-300 hover:border-white/22"
            >
              <div className="flex items-center justify-between border-b border-white/6 bg-white/[0.02] px-6 py-4">
                <div className="flex items-center gap-3">
                  <div className="rounded-full border border-white/10 bg-white/[0.04] p-2 text-white/42 transition-colors group-hover:text-white/80">
                    {themeIcon(item.topic)}
                  </div>
                  <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-white/60 transition-colors group-hover:text-white">
                    {item.label}
                  </span>
                </div>
                <span className="text-[10px] font-mono uppercase tracking-[0.16em] text-white/16">{String(index + 1).padStart(2, "0")}</span>
              </div>

              <div className="space-y-6 p-6">
                <div className="space-y-2">
                  <span className="text-[9px] font-mono uppercase tracking-[0.3em] text-white/34">전략적 맥락</span>
                  <p className="text-[13.5px] leading-7 text-white/78 transition-colors group-hover:text-white/92">
                    {summary}
                  </p>
                </div>

                {keyMetric ? (
                  <div className="rounded-[18px] border border-white/10 bg-black/40 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/34">
                        주요 지표
                      </span>
                      <div className="h-1 w-14 overflow-hidden rounded-full bg-white/10">
                        <div className="h-full w-2/3 bg-[#00ffff]/60" />
                      </div>
                    </div>
                    <p className="mt-3 text-[12px] font-mono font-bold leading-6 text-[#00ffff]">{keyMetric}</p>
                  </div>
                ) : null}

                {relatedStocks.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {relatedStocks.map((stock) => (
                      <span
                        key={stock}
                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[9px] font-mono uppercase tracking-[0.14em] text-white/46"
                      >
                        {stock}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
