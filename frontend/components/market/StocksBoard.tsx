import type { CSSProperties } from "react";

import type { MarketSnapshot, TechStock, TickerItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { RevealSection } from "@/components/ui/RevealSection";

function toneClass(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "text-[var(--accent-green)]";
  if (trend === "down") return "text-[var(--accent-down)]";
  return "text-white/55";
}

function changeMagnitude(change: string | null | undefined): number {
  if (!change) return 0;
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
      borderColor: `rgba(14,203,129,${0.24 + strength * 0.22})`,
      background: `linear-gradient(135deg, rgba(14,203,129,${0.18 + strength * 0.20}), rgba(6,20,18,0.96) 82%)`,
    };
  }
  if (trend === "down") {
    return {
      borderColor: `rgba(246,70,93,${0.24 + strength * 0.22})`,
      background: `linear-gradient(135deg, rgba(246,70,93,${0.18 + strength * 0.20}), rgba(24,8,8,0.96) 82%)`,
    };
  }
  return {
    borderColor: "rgba(255,255,255,0.08)",
    background: "linear-gradient(135deg, rgba(255,255,255,0.05), rgba(10,10,10,0.96) 82%)",
  };
}

// ─── Sparkline ───────────────────────────────────────────────────────────────

function Sparkline({
  history,
  trend,
  width = 64,
  height = 28,
}: {
  history: number[];
  trend: "up" | "down" | "neutral" | null;
  width?: number;
  height?: number;
}) {
  if (history.length < 2) return <span className="w-16" />;

  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min || 1;
  const pad = 2;

  const points = history.map((v, i) => {
    const x = pad + (i / (history.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (v - min) / range) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const color =
    trend === "up"
      ? "#0ecb81"
      : trend === "down"
        ? "#f6465d"
        : "rgba(255,255,255,0.36)";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      aria-hidden="true"
    >
      <polyline
        points={points.join(" ")}
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.82"
      />
    </svg>
  );
}

// ─── 모바일 전용 strip row ────────────────────────────────────────────────────

function MarketStripRow({ item, isLast }: { item: TickerItem; isLast: boolean }) {
  const borderColor =
    item.trend === "up"
      ? "rgba(14,203,129,0.55)"
      : item.trend === "down"
        ? "rgba(246,70,93,0.55)"
        : "rgba(255,255,255,0.12)";

  return (
    <div
      className={`grid items-center gap-3 px-4 py-3.5 ${!isLast ? "border-b border-white/6" : ""}`}
      style={{ gridTemplateColumns: "1fr 72px auto" }}
    >
      {/* 심볼 + 라벨 */}
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className="h-full w-[3px] shrink-0 self-stretch rounded-full"
            style={{ background: borderColor, minHeight: "32px" }}
          />
          <div className="min-w-0">
            <p className="numeric-sm font-semibold leading-tight text-white">{item.symbol}</p>
            <p className="mt-0.5 truncate text-[11px] text-white/40">{item.label}</p>
          </div>
        </div>
      </div>

      {/* 스파크라인 */}
      <div className="flex items-center justify-center">
        <Sparkline history={item.history} trend={item.trend} width={64} height={26} />
      </div>

      {/* 값 + 등락 */}
      <div className="text-right">
        <p className="numeric-sm font-semibold leading-tight text-white">{item.value ?? "N/A"}</p>
        <p className={`mt-0.5 text-[11px] font-medium ${toneClass(item.trend)}`}>
          {item.change ?? "—"}
          {item.isCached ? (
            <span className="ml-1 text-white/24">·</span>
          ) : null}
        </p>
      </div>
    </div>
  );
}

// ─── 데스크톱 히트맵 카드 ─────────────────────────────────────────────────────

function MetricCard({ item }: { item: TickerItem }) {
  const direction = item.trend === "up" ? "상승" : item.trend === "down" ? "하락" : "보합";
  return (
    <div className="card-family-data h-full" style={compactHeatTone(item.trend, changeMagnitude(item.change), 3.5)}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <span className="label-meta truncate text-white/46">{item.symbol}</span>
          <p className="truncate text-[13px] leading-5 text-white/78">{item.label}</p>
        </div>
        <div className="text-right">
          <span className="numeric-md block leading-tight text-white">{item.value ?? "N/A"}</span>
          <div className={`mt-1 text-[12px] ${toneClass(item.trend)}`}>
            <span>{item.change ?? direction}</span>
          </div>
        </div>
      </div>
      {item.history.length >= 2 && (
        <div className="mt-3 flex justify-end">
          <Sparkline history={item.history} trend={item.trend} width={72} height={28} />
        </div>
      )}
      {item.isCached ? (
        <p className="label-meta mt-2 text-white/28">cached</p>
      ) : null}
    </div>
  );
}

function StockCard({ stock }: { stock: TechStock }) {
  const direction = stock.trend === "up" ? "상승" : stock.trend === "down" ? "하락" : "보합";
  return (
    <div className="card-family-data h-full" style={compactHeatTone(stock.trend, stock.absChangeNum ?? changeMagnitude(stock.change), 4)}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="label-meta text-white/42">{stock.symbol}</p>
          <p className="truncate text-[13px] leading-5 text-white/74">{stock.name}</p>
        </div>
        <div className="text-right">
          <p className="numeric-md text-white">{stock.price ?? "N/A"}</p>
          <p className={`mt-1 text-[12px] ${toneClass(stock.trend)}`}>{stock.change ?? direction}</p>
        </div>
      </div>
      {stock.isCached ? (
        <p className="label-meta mt-3 text-white/28">cached</p>
      ) : null}
    </div>
  );
}

// ─── 기술주 모바일 pill strip ─────────────────────────────────────────────────

function StockPill({ stock }: { stock: TechStock }) {
  return (
    <div className="flex shrink-0 flex-col gap-1 rounded-xl border border-white/8 bg-white/[0.025] px-3 py-2.5 text-center">
      <p className="numeric-sm font-semibold text-white">{stock.symbol}</p>
      <p className="numeric-sm text-white/80">{stock.price ?? "N/A"}</p>
      <p className={`text-[11px] font-medium ${toneClass(stock.trend)}`}>{stock.change ?? "—"}</p>
    </div>
  );
}

// ─── delay helpers ────────────────────────────────────────────────────────────

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

// ─── 메인 컴포넌트 ────────────────────────────────────────────────────────────

export function StocksBoard({
  snapshot,
  stocks,
}: {
  snapshot: MarketSnapshot;
  stocks: TechStock[];
}) {
  return (
    <RevealSection className="border-b border-white/10 px-6 py-16" threshold={0.25} delayMs={220}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">

        {/* 섹션 헤더 */}
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="section-title">시장 주요 지표</h2>
            <p className="eyebrow">Quantitative Pulse</p>
          </div>
          <div className="flex items-center gap-4 text-[10px] font-mono uppercase tracking-[0.18em] text-white/42">
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--accent-green)]" />
              상승
            </span>
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--accent-down)]" />
              하락
            </span>
          </div>
        </div>

        {snapshot.items.length === 0 ? (
          <DataState
            title="시장 지표 상태"
            message="이번 집계에서는 시장 지표를 확인하지 못했어요."
            family="data"
            minHeight={160}
          />
        ) : (
          <>
            {/* 모바일: strip 리스트 */}
            <div className="overflow-hidden rounded-2xl border border-white/8 bg-black/24 md:hidden">
              {snapshot.items.map((item, index) => (
                <MarketStripRow
                  key={item.symbol}
                  item={item}
                  isLast={index === snapshot.items.length - 1}
                />
              ))}
            </div>

            {/* 데스크톱: 히트맵 카드 그리드 */}
            <div className="hidden gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 md:grid">
              {snapshot.items.map((item, index) => (
                <div
                  key={item.symbol}
                  className="card-data market-heat-card"
                  data-trend={item.trend ?? "neutral"}
                  style={{ animationDelay: metricDelayFor(index) }}
                >
                  <MetricCard item={item} />
                </div>
              ))}
            </div>
          </>
        )}

        {/* 기술주 섹션 */}
        <div>
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <p className="section-title">주요 기술주</p>
              <p className="mt-1 text-[13px] leading-6 text-[var(--text-secondary)]">
                주요 기술주의 시세와 등락을 확인합니다.
              </p>
            </div>
            <span className="label-meta text-white/26">Tech Board</span>
          </div>

          {stocks.length === 0 ? (
            <DataState
              title="기술주 보드 상태"
              message="이번 집계에서는 주요 기술주를 확인하지 못했어요."
              family="data"
              minHeight={160}
            />
          ) : (
            <>
              {/* 모바일: 가로 스크롤 pill */}
              <div className="flex gap-2.5 overflow-x-auto pb-1 md:hidden">
                {stocks.map((stock, index) => (
                  <div
                    key={stock.symbol}
                    style={{ animationDelay: stockDelayFor(index) }}
                  >
                    <StockPill stock={stock} />
                  </div>
                ))}
              </div>

              {/* 데스크톱: 카드 그리드 */}
              <div className="hidden gap-3 sm:grid-cols-2 xl:grid-cols-5 md:grid">
                {stocks.map((stock, index) => (
                  <div
                    key={stock.symbol}
                    className="card-data market-heat-card"
                    data-trend={stock.trend ?? "neutral"}
                    style={{ animationDelay: stockDelayFor(index) }}
                  >
                    <StockCard stock={stock} />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </RevealSection>
  );
}
