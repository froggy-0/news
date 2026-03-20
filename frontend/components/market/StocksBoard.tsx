import type { CSSProperties } from "react";

import type { TechStock, TickerItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

function toneColor(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") {
    return "text-[var(--accent-up)]";
  }
  if (trend === "down") {
    return "text-[var(--accent-down)]";
  }
  return "text-[var(--accent-neutral)]";
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

function changeMagnitude(change: string | null | undefined): number {
  if (!change) {
    return 0;
  }

  const match = change.match(/-?\d+(?:\.\d+)?/);
  if (!match) {
    return 0;
  }

  return Math.abs(Number(match[0]));
}

function heatCellStyle(item: TickerItem): CSSProperties {
  const magnitude = Math.min(changeMagnitude(item.change), 3.5);
  const strength = magnitude / 3.5;

  if (item.trend === "up") {
    return {
      background: `linear-gradient(135deg, rgba(2, 230, 0, ${0.08 + strength * 0.26}), rgba(19, 19, 19, 0.92) 72%)`,
      borderColor: `rgba(2, 230, 0, ${0.18 + strength * 0.32})`,
      boxShadow: `inset 0 0 0 1px rgba(2, 230, 0, ${0.08 + strength * 0.18})`,
    };
  }

  if (item.trend === "down") {
    return {
      background: `linear-gradient(135deg, rgba(248, 113, 113, ${0.08 + strength * 0.24}), rgba(19, 19, 19, 0.92) 72%)`,
      borderColor: `rgba(248, 113, 113, ${0.16 + strength * 0.28})`,
      boxShadow: `inset 0 0 0 1px rgba(248, 113, 113, ${0.08 + strength * 0.16})`,
    };
  }

  return {
    background: "linear-gradient(135deg, rgba(255, 255, 255, 0.04), rgba(19, 19, 19, 0.92) 72%)",
    borderColor: "rgba(255, 255, 255, 0.08)",
  };
}

function HeatCell({ item }: { item: TickerItem }) {
  return (
    <div
      className="rounded-[4px] border px-3 py-3 transition-transform duration-200 hover:scale-[1.02]"
      style={heatCellStyle(item)}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)]">
            {item.symbol}
          </p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">{item.label}</p>
        </div>
        <p className={`font-mono text-[10px] ${toneColor(item.trend)}`}>{item.change ?? "상태 확인"}</p>
      </div>
      <p className="numeric mt-3 text-xl text-[var(--text-primary)]">{item.value ?? "확인 중"}</p>
      <div className="mt-3">
        <Sparkline
          data={item.history}
          color={
            item.trend === "down"
              ? "rgba(248,113,113,0.95)"
              : item.trend === "up"
                ? "rgba(2,230,0,0.95)"
                : "rgba(229,226,225,0.72)"
          }
        />
      </div>
    </div>
  );
}

function MobileIndexCell({ item }: { item: TickerItem }) {
  return (
    <div className="rounded-[4px] border px-3 py-3" style={heatCellStyle(item)}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)]">{item.symbol}</p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">{item.label}</p>
        </div>
        <p className={`font-mono text-[10px] ${toneColor(item.trend)}`}>{item.change ?? "확인 중"}</p>
      </div>
      <p className="numeric text-lg text-[var(--text-primary)]">{item.value ?? "확인 중"}</p>
    </div>
  );
}

function EquityCell({ stock }: { stock: TechStock }) {
  return (
    <div className="rounded-[4px] border border-white/8 bg-white/[0.03] px-3 py-3 transition-transform duration-200 hover:scale-[1.02]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] tracking-[0.18em] text-[var(--text-muted)]">
            {stock.symbol}
          </p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">{stock.name}</p>
        </div>
        <p className={`font-mono text-[10px] ${toneColor(stock.trend)}`}>{stock.change ?? "상태 확인"}</p>
      </div>
      <p className="numeric mt-3 text-xl text-[var(--text-primary)]">{stock.price ?? "확인 중"}</p>
      {stock.isCached ? (
        <p className="mt-2 font-mono text-[9px] tracking-[0.16em] text-[var(--text-muted)]">CACHED</p>
      ) : null}
    </div>
  );
}

export function StocksBoard({
  indices,
  stocks,
}: {
  indices: TickerItem[];
  stocks: TechStock[];
}) {
  return (
    <section className="space-y-6">
      <div className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
        <div className="mb-6 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="h-2 w-2 rounded-full bg-[var(--accent-primary)]" />
            <p className="section-title">미국 증시 흐름</p>
          </div>
          <p className="eyebrow">핵심 지수</p>
        </div>
        {indices.length === 0 ? (
          <DataState message="이번 집계에서는 미국 지수 흐름을 확인하지 못했어요." />
        ) : (
          <>
            <div className="grid gap-3 md:hidden">
              {indices.map((item) => (
                <MobileIndexCell key={item.symbol} item={item} />
              ))}
            </div>
            <div className="hidden gap-3 md:grid xl:grid-cols-3">
              {indices.map((item) => (
                <HeatCell key={item.symbol} item={item} />
              ))}
            </div>
          </>
        )}
      </div>

      <div className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
        <div className="mb-6 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="h-2 w-2 rounded-full bg-[var(--accent-primary)]" />
            <p className="section-title">주요 기술주</p>
          </div>
          <p className="eyebrow">테크 보드</p>
        </div>
        {stocks.length === 0 ? (
          <DataState message="이번 집계에서는 주요 기술주를 확인하지 못했어요." />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {stocks.map((stock) => (
              <EquityCell key={stock.symbol} stock={stock} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
