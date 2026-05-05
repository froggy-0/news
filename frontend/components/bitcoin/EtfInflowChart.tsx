"use client";

import { useEffect, useRef, useState } from "react";

import type { EtfHistoryPoint } from "@schema/brief.types";

// lightweight-charts v5 — Canvas 기반, SSR 불가 → dynamic import로만 사용
type LCModule = typeof import("lightweight-charts");

const GREEN = "#0ecb81";
const RED = "#f6465d";
const MUTED = "rgba(255,255,255,0.22)";

function formatBtc(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1000) return `${(n / 1000).toFixed(1)}K BTC`;
  return `${n > 0 ? "+" : ""}${n.toFixed(0)} BTC`;
}

function formatAum(usd: number): string {
  const b = usd / 1_000_000_000;
  return `$${b.toFixed(1)}B`;
}

function formatDate(iso: string): string {
  const [, mm, dd] = iso.split("-");
  return `${mm}/${dd}`;
}

function TooltipCard({
  point,
  visible,
  x,
}: {
  point: EtfHistoryPoint | null;
  visible: boolean;
  x: number;
}) {
  if (!visible || !point) return null;
  const delta = point.deltaBtc;
  const isPositive = delta !== null && delta >= 0;
  const color = delta === null ? MUTED : isPositive ? GREEN : RED;

  return (
    <div
      className="pointer-events-none absolute top-3 z-10 min-w-[148px] rounded-xl border border-white/10 bg-[rgba(11,10,8,0.92)] px-3.5 py-3 backdrop-blur-md"
      style={{ left: Math.min(x, 999) }}
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/36">
        {formatDate(point.date)}
      </p>
      {delta !== null ? (
        <p className="mt-1.5 font-mono text-sm font-bold" style={{ color }}>
          {formatBtc(delta)}
        </p>
      ) : (
        <p className="mt-1.5 font-mono text-xs text-white/30">기준일 없음</p>
      )}
      <p className="mt-1 font-mono text-[11px] text-white/42">{formatAum(point.totalAumUsd)}</p>
    </div>
  );
}

export function EtfInflowChart({ history }: { history: EtfHistoryPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<LCModule["createChart"]> | null>(null);

  const [tooltip, setTooltip] = useState<{
    visible: boolean;
    point: EtfHistoryPoint | null;
    x: number;
  }>({ visible: false, point: null, x: 0 });

  // 유효 delta만 있는 포인트 필터 (첫 포인트는 delta 없음)
  const chartData = history
    .filter((p) => p.deltaBtc !== null)
    .map((p) => ({
      time: p.date as `${number}-${number}-${number}`,
      value: p.deltaBtc!,
      color: p.deltaBtc! >= 0 ? `${GREEN}cc` : `${RED}cc`,
    }));

  useEffect(() => {
    if (!containerRef.current || chartData.length === 0) return;

    let chart: ReturnType<LCModule["createChart"]>;
    let resizeObserver: ResizeObserver;

    import("lightweight-charts").then((lc) => {
      if (!containerRef.current) return;

      const container = containerRef.current;
      const w = container.clientWidth;
      const h = 200;

      chart = lc.createChart(container, {
        width: w,
        height: h,
        layout: {
          background: { color: "transparent" },
          textColor: "rgba(255,255,255,0.38)",
          fontFamily: "'IBM Plex Mono', 'JetBrains Mono', monospace",
          fontSize: 10,
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        crosshair: {
          vertLine: {
            color: "rgba(255,255,255,0.22)",
            width: 1,
            style: 3,
            labelBackgroundColor: "#1a1916",
          },
          horzLine: {
            color: "rgba(255,255,255,0.22)",
            width: 1,
            style: 3,
            labelBackgroundColor: "#1a1916",
          },
        },
        rightPriceScale: {
          borderColor: "rgba(255,255,255,0.06)",
          scaleMargins: { top: 0.08, bottom: 0.08 },
        },
        timeScale: {
          borderColor: "rgba(255,255,255,0.06)",
          timeVisible: false,
          fixLeftEdge: true,
          fixRightEdge: true,
        },
        handleScroll: false,
        handleScale: false,
      });

      const series = chart.addSeries(lc.HistogramSeries, {
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "custom", formatter: (v: number) => formatBtc(v) },
      });

      series.setData(chartData);
      chart.timeScale().fitContent();

      // 크로스헤어 hover → 커스텀 툴팁 동기화
      chart.subscribeCrosshairMove((param) => {
        if (!param.point || !param.time) {
          setTooltip((t) => ({ ...t, visible: false }));
          return;
        }
        const isoDate = typeof param.time === "string" ? param.time : String(param.time);
        const matched = history.find((p) => p.date === isoDate) ?? null;
        const rawX = param.point.x;
        // 툴팁이 오른쪽 끝에 붙지 않도록 위치 조정
        const tipX = rawX + 16 > w - 180 ? rawX - 164 : rawX + 16;
        setTooltip({ visible: true, point: matched, x: tipX });
      });

      chartRef.current = chart;

      resizeObserver = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      resizeObserver.observe(container);
    });

    return () => {
      resizeObserver?.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (chartData.length === 0) return null;

  // 가장 최근 delta 요약 (헤더용)
  const latest = history.at(-1);
  const latestDelta = latest?.deltaBtc ?? null;
  const deltaColor = latestDelta === null ? MUTED : latestDelta >= 0 ? GREEN : RED;

  return (
    <div className="mt-6">
      {/* 서브헤더 */}
      <div className="mb-3 flex items-baseline justify-between">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-white/30">
          일별 BTC 순유입 ({chartData.length}일)
        </p>
        {latestDelta !== null && (
          <p className="font-mono text-xs font-bold" style={{ color: deltaColor }}>
            오늘 {formatBtc(latestDelta)}
          </p>
        )}
      </div>

      {/* 차트 컨테이너 */}
      <div className="relative w-full overflow-hidden rounded-xl border border-white/6 bg-[rgba(0,0,0,0.28)]">
        <div ref={containerRef} className="w-full" style={{ height: 200 }} />
        <TooltipCard
          point={tooltip.point}
          visible={tooltip.visible}
          x={tooltip.x}
        />
      </div>

      {/* 범례 */}
      <div className="mt-2.5 flex gap-4">
        <span className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-white/28">
          <span className="h-1.5 w-3 rounded-full" style={{ background: GREEN }} />
          유입
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-white/28">
          <span className="h-1.5 w-3 rounded-full" style={{ background: RED }} />
          유출
        </span>
      </div>
    </div>
  );
}
