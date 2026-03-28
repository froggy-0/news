"use client";

import React, { useEffect, useRef, useState } from "react";
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

function themeAccent(topic: TopicSummary["topic"]): string {
  if (topic === "macro") return "from-[#9dff73]/90 to-[#00ff66]/18";
  if (topic === "us-stocks") return "from-[#00ffff]/90 to-[#00ffff]/18";
  if (topic === "bigtech") return "from-[#ffd36b]/88 to-[#ffd36b]/16";
  if (topic === "bitcoin") return "from-[#ffb45c]/88 to-[#ff8a3d]/16";
  return "from-white/55 to-white/10";
}

function animationDelayFor(index: number): string {
  if (index === 0) return "100ms";
  if (index === 1) return "760ms";
  if (index === 2) return "1180ms";
  return "1380ms";
}

export function TopicGrid({
  items,
  variant = "detail",
}: {
  items: TopicSummary[];
  variant?: "home" | "detail";
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [cardsActivated, setCardsActivated] = useState(false);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node || cardsActivated) {
      return;
    }

    let activationTimer: ReturnType<typeof setTimeout> | null = null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          activationTimer = setTimeout(() => {
            setCardsActivated(true);
          }, 180);
          observer.disconnect();
        }
      },
      { threshold: 0.34 },
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      if (activationTimer) {
        clearTimeout(activationTimer);
      }
    };
  }, [cardsActivated]);

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
    <section ref={sectionRef} id="map" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="flex flex-col gap-1">
            <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">오늘의 주요 테마</h2>
            <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
              Contextual Analysis
            </span>
          </div>
          <p className="max-w-md text-[15px] leading-7 text-white/66">
            오늘 장을 해석하는 네 개의 축을 먼저 제시하고, 그 뒤에 숫자와 기사로 내려갑니다.
          </p>
        </div>
        <div className={`grid gap-6 ${variant === "home" ? "md:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-2"}`}>
          {visibleItems.map(({ item, summary, keyMetric, relatedStocks }, index) => (
            <article
              key={item.topic}
              className={`card-reading theme-card ${cardsActivated ? "theme-card--active" : ""} group relative overflow-hidden rounded-[26px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.015))] transition-colors duration-300 hover:border-white/22 ${
                variant === "home" && index === 0 ? "md:col-span-2 xl:col-span-2" : ""
              }`}
              style={{ animationDelay: animationDelayFor(index) }}
            >
              <div className={`theme-card-accent-x absolute left-0 top-0 h-px w-full bg-gradient-to-r ${themeAccent(item.topic)}`} />
              <div className={`theme-card-accent-y absolute left-0 top-0 h-full w-px bg-gradient-to-b ${themeAccent(item.topic)}`} />

              <div className={`space-y-6 p-6 md:p-7 ${variant === "home" && index === 0 ? "xl:p-8" : ""}`}>
                <div className="flex items-center gap-3">
                  <div className="rounded-full border border-white/10 bg-white/[0.03] p-2 text-white/38 transition-colors group-hover:text-white/70">
                    {themeIcon(item.topic)}
                  </div>
                  <div className="min-w-0">
                    <p className="text-[10px] font-mono uppercase tracking-[0.26em] text-white/28">
                      {String(index + 1).padStart(2, "0")}
                    </p>
                    <h3 className="card-reading-meta mt-1 text-[12px] font-mono uppercase tracking-[0.24em] text-white/70">
                      {item.label}
                    </h3>
                  </div>
                </div>

                <div className={`space-y-3 ${variant === "home" && index === 0 ? "max-w-2xl" : ""}`}>
                  <span className="text-[9px] font-mono uppercase tracking-[0.3em] text-white/30">전략적 맥락</span>
                  <p
                    className={`card-reading-copy theme-card-copy text-white/90 transition-colors group-hover:text-white ${
                      variant === "home" && index === 0
                        ? "text-[16px] leading-8 md:text-[18px] md:leading-9"
                        : "text-[15px] leading-8"
                    }`}
                  >
                    {summary}
                  </p>
                </div>

                {(keyMetric || relatedStocks.length > 0) && (
                  <div className="flex flex-col gap-3 border-t border-white/8 pt-4">
                    {keyMetric ? (
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/30">
                          핵심 수치
                        </span>
                        <p className="card-reading-meta text-[12px] font-mono leading-6 text-white/76">{keyMetric}</p>
                      </div>
                    ) : null}

                    {relatedStocks.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/24">
                          Related
                        </span>
                        {relatedStocks.map((stock) => (
                          <span
                            key={stock}
                            className="card-reading-meta text-[10px] font-mono uppercase tracking-[0.16em] text-white/44"
                          >
                            {stock}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
