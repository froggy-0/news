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

function heatToneStyle(
  trend: "up" | "down" | "neutral" | null,
  magnitude: number,
  maxMagnitude: number,
): CSSProperties {
  const strength = Math.min(magnitude, maxMagnitude) / maxMagnitude;

  if (trend === "up") {
    return {
      background: `linear-gradient(135deg, rgba(0, 255, 255, ${0.08 + strength * 0.24}), rgba(10, 10, 10, 0.94) 74%)`,
      borderColor: `rgba(0, 255, 255, ${0.16 + strength * 0.22})`,
    };
  }

  if (trend === "down") {
    return {
      background: `linear-gradient(135deg, rgba(255, 107, 107, ${0.08 + strength * 0.24}), rgba(10, 10, 10, 0.94) 74%)`,
      borderColor: `rgba(255, 107, 107, ${0.16 + strength * 0.22})`,
    };
  }

  return {
    background: "linear-gradient(135deg, rgba(255,255,255,0.04), rgba(10,10,10,0.94) 74%)",
    borderColor: "rgba(255,255,255,0.08)",
  };
}

function sparklineColor(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "rgba(0,255,255,0.95)";
  if (trend === "down") return "rgba(255,107,107,0.95)";
  return "rgba(255,255,255,0.6)";
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) {
    return null;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const width = 84;
  const height = 24;
  const points = data
    .map((value, index) => {
      const x = (index / (data.length - 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

function MetricCard({ item }: { item: TickerItem }) {
  return (
    <div
      className="overflow-hidden border p-4 transition-transform duration-300 hover:scale-[1.01]"
      style={heatToneStyle(item.trend, changeMagnitude(item.change), 3.5)}
    >
      <div className="flex flex-col gap-0.5">
        <span className="truncate text-[8px] font-mono uppercase tracking-[0.16em] text-white/52">
          {item.label}
        </span>
        <span className="text-lg font-mono leading-tight text-white">{item.value ?? "N/A"}</span>
        <div className={`flex items-center gap-1 text-[9px] font-mono ${toneClass(item.trend)}`}>
          <span>{item.change ?? "변동 없음"}</span>
        </div>
      </div>
      {item.history.length >= 2 ? (
        <div className="mt-4">
          <Sparkline data={item.history} color={sparklineColor(item.trend)} />
        </div>
      ) : null}
      {item.isCached ? (
        <p className="mt-3 text-[8px] font-mono uppercase tracking-[0.22em] text-white/28">cached</p>
      ) : null}
    </div>
  );
}

function StockCard({ stock }: { stock: TechStock }) {
  return (
    <div
      className="border p-4 transition-transform duration-300 hover:scale-[1.01]"
      style={heatToneStyle(stock.trend, stock.absChangeNum ?? changeMagnitude(stock.change), 4)}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-white/36">
            {stock.symbol}
          </p>
          <p className="mt-1 text-sm text-white/72">{stock.name}</p>
        </div>
        <p className={`text-[10px] font-mono ${toneClass(stock.trend)}`}>{stock.change ?? "0.00%"}</p>
      </div>
      <p className="numeric mt-3 text-xl text-white">{stock.price ?? "N/A"}</p>
      {stock.isCached ? (
        <p className="mt-3 text-[8px] font-mono uppercase tracking-[0.22em] text-white/28">cached</p>
      ) : null}
    </div>
  );
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
  return (
    <section className="border-b border-white/10 px-6 py-16">
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
        </div>

        {snapshot.items.length === 0 ? (
          <DataState message="이번 집계에서는 시장 지표를 확인하지 못했어요." />
        ) : (
          <div className={`grid gap-3 ${variant === "home" ? "sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7" : "sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7"}`}>
            {snapshot.items.map((item) => (
              <MetricCard key={item.symbol} item={item} />
            ))}
          </div>
        )}

        <div className="section-shell rounded-[28px] p-6">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div>
              <p className="section-title">주요 기술주</p>
              <p className="mt-2 text-sm leading-7 text-white/58">
                홈에서는 고빈도 종목만 빠르게 스캔하고, 상세에서도 동일한 보드 체계를 유지합니다.
              </p>
            </div>
            <span className="text-[9px] font-mono uppercase tracking-[0.22em] text-white/26">Tech Board</span>
          </div>
          {stocks.length === 0 ? (
            <DataState message="이번 집계에서는 주요 기술주를 확인하지 못했어요." />
          ) : (
            <div className={`grid gap-3 ${variant === "home" ? "md:grid-cols-2 xl:grid-cols-5" : "md:grid-cols-2 xl:grid-cols-5"}`}>
              {stocks.map((stock) => (
                <StockCard key={stock.symbol} stock={stock} />
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
