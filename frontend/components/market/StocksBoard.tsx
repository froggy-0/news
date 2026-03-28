"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import type { MarketSnapshot, TechStock, TickerItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

function toneClass(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "text-[#00ffff]";
  if (trend === "down") return "text-[#ff6b6b]";
  return "text-white/55";
}

function changeMagnitude(change: string | null | undefined): number {
  if (!change) {
    return 0;
  }
  const match = change.match(/-?\d+(?:\.\d+)?/);
  return match ? Math.abs(Number(match[0])) : 0;
}

function compactHeatTone(
  trend: "up" | "down" | "neutral" | null,
  magnitude: number,
  maxMagnitude: number,
): CSSProperties {
  const strength = Math.min(magnitude, maxMagnitude) / maxMagnitude;

  if (trend === "up") {
    return {
      borderColor: `rgba(0,255,170,${0.24 + strength * 0.22})`,
      background: `linear-gradient(135deg, rgba(0,255,170,${0.2 + strength * 0.22}), rgba(6,20,18,0.96) 82%)`,
    };
  }

  if (trend === "down") {
    return {
      borderColor: `rgba(255,107,107,${0.24 + strength * 0.22})`,
      background: `linear-gradient(135deg, rgba(255,107,107,${0.2 + strength * 0.22}), rgba(24,8,8,0.96) 82%)`,
    };
  }

  return {
    borderColor: "rgba(255,255,255,0.08)",
    background: "linear-gradient(135deg, rgba(255,255,255,0.05), rgba(10,10,10,0.96) 82%)",
  };
}

function MetricCard({ item }: { item: TickerItem }) {
  const direction = item.trend === "up" ? "상승" : item.trend === "down" ? "하락" : "보합";
  return (
    <div
      className="border px-3 py-2.5"
      style={compactHeatTone(item.trend, changeMagnitude(item.change), 3.5)}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="truncate text-[8px] font-mono uppercase tracking-[0.16em] text-white/46">
            {item.symbol}
          </span>
          <p className="truncate text-[11px] text-white/72">{item.label}</p>
        </div>
        <div className="text-right">
          <span className="block text-base font-mono leading-tight text-white">{item.value ?? "N/A"}</span>
          <div className={`mt-0.5 text-[9px] font-mono ${toneClass(item.trend)}`}>
            <span>{item.change ?? direction}</span>
          </div>
        </div>
      </div>
      {item.isCached ? (
        <p className="mt-2 text-[7px] font-mono uppercase tracking-[0.22em] text-white/28">cached</p>
      ) : null}
    </div>
  );
}

function StockCard({ stock }: { stock: TechStock }) {
  const direction = stock.trend === "up" ? "상승" : stock.trend === "down" ? "하락" : "보합";
  return (
    <div
      className="border px-3 py-2.5"
      style={compactHeatTone(stock.trend, stock.absChangeNum ?? changeMagnitude(stock.change), 4)}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[9px] font-mono uppercase tracking-[0.18em] text-white/42">
            {stock.symbol}
          </p>
          <p className="truncate text-[11px] text-white/70">{stock.name}</p>
        </div>
        <div className="text-right">
          <p className="numeric text-base text-white">{stock.price ?? "N/A"}</p>
          <p className={`text-[9px] font-mono ${toneClass(stock.trend)}`}>{stock.change ?? direction}</p>
        </div>
      </div>
      {stock.isCached ? (
        <p className="mt-2 text-[7px] font-mono uppercase tracking-[0.22em] text-white/28">cached</p>
      ) : null}
    </div>
  );
}

function metricDelayFor(index: number): string {
  if (index === 0) return "140ms";
  if (index === 1) return "620ms";
  if (index === 2) return "920ms";
  return "1140ms";
}

function stockDelayFor(index: number): string {
  const delays = ["180ms", "560ms", "760ms", "930ms", "1090ms", "1240ms"];
  return delays[index] ?? `${1240 + index * 120}ms`;
}

export function StocksBoard({
  snapshot,
  stocks,
  variant = "home",
}: {
  snapshot: MarketSnapshot;
  stocks: TechStock[];
  variant?: "home" | "detail";
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [metricsActivated, setMetricsActivated] = useState(false);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node || metricsActivated) {
      return;
    }

    let activationTimer: ReturnType<typeof setTimeout> | null = null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          activationTimer = setTimeout(() => {
            setMetricsActivated(true);
          }, 220);
          observer.disconnect();
        }
      },
      { threshold: 0.38 },
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      if (activationTimer) {
        clearTimeout(activationTimer);
      }
    };
  }, [metricsActivated]);

  const compactMetrics = variant === "home" ? snapshot.items.slice(0, 4) : snapshot.items;
  const compactStocks = variant === "home" ? stocks.slice(0, 6) : stocks;
  return (
    <section ref={sectionRef} className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="text-[11px] font-mono uppercase tracking-[0.3em] text-white/60">
              시장 주요 지표
            </h2>
            <p className="text-[9px] font-mono uppercase tracking-[0.24em] text-white/28">
              Quantitative Pulse
            </p>
          </div>
          {variant === "detail" ? (
            <div className="flex items-center gap-4 text-[10px] font-mono uppercase tracking-[0.18em] text-white/42">
              <span className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-[#00ffff]" />
                상승
              </span>
              <span className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-[#ff6b6b]" />
                하락
              </span>
            </div>
          ) : (
            <p className="max-w-md text-sm leading-7 text-white/52">
              티커와 방향만 빠르게 훑고, 자세한 맥락은 뉴스에서 읽도록 압축했습니다.
            </p>
          )}
        </div>

        {compactMetrics.length === 0 ? (
          <DataState message="이번 집계에서는 시장 지표를 확인하지 못했어요." />
        ) : (
          <div
            className={`grid grid-cols-2 gap-3 ${
              variant === "home" ? "lg:grid-cols-4" : "lg:grid-cols-4 xl:grid-cols-7"
            }`}
          >
            {compactMetrics.map((item, index) => (
              <div
                key={item.symbol}
                className={metricsActivated ? "card-data market-heat-card market-heat-card--active" : "card-data market-heat-card"}
                data-trend={item.trend ?? "neutral"}
                style={{ animationDelay: metricDelayFor(index) }}
              >
                <MetricCard item={item} />
              </div>
            ))}
          </div>
        )}

        <div>
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <p className="section-title">주요 기술주</p>
              <p className="mt-1 text-[12px] leading-5 text-white/58">
                {variant === "home"
                  ? "대표 종목의 가격과 방향만 빠르게 확인합니다."
                  : "홈에서는 고빈도 종목만 빠르게 스캔하고, 상세에서도 동일한 보드 체계를 유지합니다."}
              </p>
            </div>
            <span className="text-[9px] font-mono uppercase tracking-[0.22em] text-white/26">Tech Board</span>
          </div>
          {compactStocks.length === 0 ? (
            <DataState message="이번 집계에서는 주요 기술주를 확인하지 못했어요." />
          ) : (
            <div className={`grid grid-cols-2 gap-3 ${variant === "home" ? "lg:grid-cols-3" : "xl:grid-cols-5"}`}>
              {compactStocks.map((stock, index) => (
                <div
                  key={stock.symbol}
                  className={metricsActivated ? "card-data market-heat-card market-heat-card--active" : "card-data market-heat-card"}
                  data-trend={stock.trend ?? "neutral"}
                  style={{ animationDelay: stockDelayFor(index) }}
                >
                  <StockCard stock={stock} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
