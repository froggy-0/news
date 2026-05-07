"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

import type { EtfHistoryPoint } from "@schema/brief.types";

type LCModule = typeof import("lightweight-charts");
type RangeKey = "7D" | "14D" | "30D" | "ALL";

const GREEN = "#0ecb81";
const RED = "#f6465d";
const YELLOW = "#f0b90b";
const MUTED = "rgba(255,255,255,0.36)";
const CHART_HEIGHT_DESKTOP = 240;
const CHART_HEIGHT_MOBILE = 290;
const RANGE_OPTIONS: Array<{ key: RangeKey; days: number | null }> = [
  { key: "7D", days: 7 },
  { key: "14D", days: 14 },
  { key: "30D", days: 30 },
  { key: "ALL", days: null },
];

function initialRange(length: number): RangeKey {
  return length >= 14 ? "14D" : "ALL";
}

function rangeEnabled(length: number, days: number | null): boolean {
  return days === null || length >= days;
}

function selectedSlice(history: EtfHistoryPoint[], range: RangeKey): EtfHistoryPoint[] {
  const option = RANGE_OPTIONS.find((item) => item.key === range);
  if (!option?.days) return history;
  return history.slice(-option.days);
}

function formatSignedBtc(value: number | null | undefined): string {
  if (value === null || value === undefined) return "확인 중";
  const abs = Math.abs(value);
  const formatted = abs >= 1000 ? `${(abs / 1000).toFixed(1)}K BTC` : `${abs.toFixed(0)} BTC`;
  if (value === 0) return "0 BTC";
  return `${value > 0 ? "+" : "-"}${formatted}`;
}

function formatBtcAmount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "확인 중";
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}K BTC`;
  return `${value.toFixed(0)} BTC`;
}

function formatAum(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "확인 중";
  const b = usd / 1_000_000_000;
  return `$${b.toFixed(1)}B`;
}

function formatDate(iso: string): string {
  const [, mm, dd] = iso.split("-");
  return `${mm}/${dd}`;
}

function flowTone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return MUTED;
  return value > 0 ? GREEN : RED;
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

  return (
    <div
      className="pointer-events-none absolute top-3 z-20 min-w-[184px] rounded-lg border border-[#2b3139] bg-[#181a20]/95 px-3.5 py-3 shadow-[0_18px_42px_rgba(0,0,0,0.42)] backdrop-blur-md"
      style={{ left: x }}
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/42">
        {formatDate(point.date)}
      </p>
      <div className="mt-2 space-y-1.5">
        <TooltipRow label="순유입" value={formatSignedBtc(delta)} color={flowTone(delta)} />
        <TooltipRow label="총 보유 BTC" value={formatBtcAmount(point.totalBtc)} />
        <TooltipRow label="총 AUM" value={formatAum(point.totalAumUsd)} />
      </div>
    </div>
  );
}

function TooltipRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-[11px] leading-5 text-white/42">{label}</span>
      <span className="font-mono text-[11px] font-bold leading-5 text-white/78" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md border border-[#2b3139] bg-[#181a20] px-3.5 py-3">
      <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-[#848e9c]">{label}</p>
      <p className="mt-1.5 font-mono text-[13px] font-bold text-[#eaecef]" style={tone ? { color: tone } : undefined}>
        {value}
      </p>
    </div>
  );
}

export function EtfInflowChart({ history }: { history: EtfHistoryPoint[] }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<LCModule["createChart"]> | null>(null);
  const frameRef = useRef<number | null>(null);

  const [range, setRange] = useState<RangeKey>(() => initialRange(history.length));
  const [hasEntered, setHasEntered] = useState(false);
  const [chartReady, setChartReady] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [tooltip, setTooltip] = useState<{
    visible: boolean;
    point: EtfHistoryPoint | null;
    x: number;
  }>({ visible: false, point: null, x: 0 });

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 639px)");
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const chartHeight = isMobile ? CHART_HEIGHT_MOBILE : CHART_HEIGHT_DESKTOP;

  useEffect(() => {
    const selectedOption = RANGE_OPTIONS.find((item) => item.key === range);
    if (selectedOption && !rangeEnabled(history.length, selectedOption.days)) {
      setRange(initialRange(history.length));
    }
  }, [history.length, range]);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    if (!("IntersectionObserver" in window)) {
      setHasEntered(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setHasEntered(true);
          observer.disconnect();
        }
      },
      { rootMargin: "160px 0px", threshold: 0.18 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const visibleHistory = useMemo(() => selectedSlice(history, range), [history, range]);
  const histogramData = useMemo(
    () =>
      visibleHistory
        .filter((point) => point.deltaBtc !== null)
        .map((point) => ({
          time: point.date as `${number}-${number}-${number}`,
          value: point.deltaBtc!,
          color: point.deltaBtc! >= 0 ? `${GREEN}d9` : `${RED}d9`,
        })),
    [visibleHistory],
  );
  const holdingData = useMemo(
    () =>
      visibleHistory.map((point) => ({
        time: point.date as `${number}-${number}-${number}`,
        value: point.totalBtc,
      })),
    [visibleHistory],
  );

  useEffect(() => {
    if (!hasEntered || !containerRef.current || histogramData.length === 0 || holdingData.length < 2) return;

    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;
    setChartReady(false);

    import("lightweight-charts").then((lc) => {
      if (cancelled || !containerRef.current) return;

      const container = containerRef.current;
      const mobile = container.clientWidth < 640;
      const chart = lc.createChart(container, {
        width: container.clientWidth,
        height: chartHeight,
        autoSize: false,
        layout: {
          background: { color: "#0b0e11" },
          textColor: "rgba(234,236,239,0.48)",
          fontFamily: "'IBM Plex Mono', 'JetBrains Mono', monospace",
          fontSize: 10,
        },
        grid: {
          vertLines: { color: "rgba(132,142,156,0.08)" },
          horzLines: { color: "rgba(132,142,156,0.08)" },
        },
        crosshair: {
          vertLine: {
            color: "rgba(240,185,11,0.42)",
            width: 1,
            style: 3,
            labelBackgroundColor: "#1e2329",
          },
          horzLine: {
            color: mobile ? "transparent" : "rgba(132,142,156,0.22)",
            width: 1,
            style: 3,
            labelBackgroundColor: "#1e2329",
            labelVisible: !mobile,
          },
        },
        leftPriceScale: {
          visible: !mobile,
          borderColor: "rgba(132,142,156,0.14)",
          textColor: "rgba(132,142,156,0.72)",
          scaleMargins: { top: 0.18, bottom: 0.2 },
        },
        rightPriceScale: {
          visible: !mobile,
          borderColor: "rgba(132,142,156,0.14)",
          textColor: "rgba(132,142,156,0.72)",
          scaleMargins: { top: 0.12, bottom: 0.28 },
        },
        timeScale: {
          borderColor: "rgba(132,142,156,0.14)",
          timeVisible: true,
          fixLeftEdge: true,
          fixRightEdge: true,
          tickMarkFormatter: (time: unknown) => {
            const iso = typeof time === "string" ? time : String(time);
            const [, mm, dd] = iso.split("-");
            return `${mm}/${dd}`;
          },
        },
        handleScroll: false,
        handleScale: false,
      });

      const flowSeries = chart.addSeries(lc.HistogramSeries, {
        priceScaleId: "left",
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "custom", formatter: (value: number) => formatSignedBtc(value) },
      });
      const holdingSeries = chart.addSeries(lc.AreaSeries, {
        priceScaleId: "right",
        lineColor: YELLOW,
        topColor: "rgba(240,185,11,0.26)",
        bottomColor: "rgba(240,185,11,0.02)",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "custom", formatter: (value: number) => formatBtcAmount(value) },
      });

      const maxLength = Math.max(histogramData.length, holdingData.length);
      const frames = 18;
      let frame = 0;
      const draw = () => {
        if (cancelled) return;
        frame += 1;
        const count = Math.max(1, Math.ceil((maxLength * frame) / frames));
        flowSeries.setData(histogramData.slice(0, count));
        holdingSeries.setData(holdingData.slice(0, count));
        if (frame < frames) {
          frameRef.current = requestAnimationFrame(draw);
        } else {
          chart.timeScale().fitContent();
          setChartReady(true);
        }
      };
      frameRef.current = requestAnimationFrame(draw);

      chart.subscribeCrosshairMove((param) => {
        if (!param.point || !param.time) {
          setTooltip((current) => ({ ...current, visible: false }));
          return;
        }
        const isoDate = typeof param.time === "string" ? param.time : String(param.time);
        const matched = visibleHistory.find((point) => point.date === isoDate) ?? null;
        const rawX = param.point.x;
        const tipWidth = 184;
        const tipX =
          rawX + tipWidth + 14 > container.clientWidth
            ? Math.max(8, rawX - tipWidth - 8)
            : rawX + 14;
        setTooltip({ visible: true, point: matched, x: tipX });
      });

      chartRef.current = chart;
      resizeObserver = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          const w = containerRef.current.clientWidth;
          const h = w < 640 ? CHART_HEIGHT_MOBILE : CHART_HEIGHT_DESKTOP;
          chartRef.current.applyOptions({ width: w, height: h });
          chartRef.current.timeScale().fitContent();
        }
      });
      resizeObserver.observe(container);
    });

    return () => {
      cancelled = true;
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      resizeObserver?.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
      frameRef.current = null;
      setTooltip((current) => ({ ...current, visible: false }));
    };
  }, [hasEntered, histogramData, holdingData, visibleHistory, isMobile, chartHeight]);

  if (history.length < 2 || histogramData.length === 0) return null;

  const latest = history.at(-1);
  const latestDelta = latest?.deltaBtc ?? null;
  const periodFlow = visibleHistory.reduce((sum, point) => sum + (point.deltaBtc ?? 0), 0);
  const periodTone = flowTone(periodFlow);

  return (
    <div ref={rootRef} className="mt-6 rounded-lg border border-[#2b3139] bg-[#0b0e11] shadow-[0_22px_54px_rgba(0,0,0,0.38)]">
      {/* 헤더 + 필터 */}
      <div className="flex flex-col gap-3 p-4 md:flex-row md:items-end md:justify-between md:p-5">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-[#848e9c]">
            ETF Flow Timeseries
          </p>
          <p className="mt-1 text-sm font-semibold leading-6 text-[#eaecef]">
            일별 순유입과 누적 보유량
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {RANGE_OPTIONS.map((option) => {
            const disabled = !rangeEnabled(history.length, option.days);
            const active = range === option.key;
            return (
              <button
                key={option.key}
                type="button"
                disabled={disabled}
                aria-pressed={active}
                onClick={() => setRange(option.key)}
                className={`h-8 min-w-12 rounded-md border px-3 font-mono text-[11px] font-bold transition-colors duration-200 ${
                  active
                    ? "border-[#f0b90b] bg-[#f0b90b] text-black"
                    : "border-[#2b3139] bg-[#181a20] text-[#848e9c] hover:border-[#f0b90b]/60 hover:text-[#eaecef]"
                } disabled:cursor-not-allowed disabled:border-[#2b3139] disabled:bg-[#111418] disabled:text-[#474d57]`}
              >
                {option.key}
              </button>
            );
          })}
        </div>
      </div>

      {/* 차트 — 모바일에서 좌우 패딩 없이 full-width */}
      <div className="relative overflow-hidden border-t border-[#2b3139] bg-[#0b0e11]">
        <div className="absolute inset-x-0 top-0 z-10 h-px bg-gradient-to-r from-transparent via-[#f0b90b]/70 to-transparent" />
        {hasEntered ? (
          <div
            ref={containerRef}
            className={`w-full transition-all duration-300 ${chartReady ? "translate-y-0 opacity-100" : "translate-y-2 opacity-40"}`}
            style={{ height: chartHeight }}
          />
        ) : (
          <ChartSkeleton height={chartHeight} />
        )}
        {hasEntered && !chartReady ? <ChartSkeleton height={chartHeight} overlay /> : null}
        <TooltipCard point={tooltip.point} visible={tooltip.visible} x={tooltip.x} />
      </div>

      {/* 범례 + 서머리 — 차트 아래 */}
      <div className="p-4 md:p-5">
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          <LegendDot color={GREEN} label="일별 유입" />
          <LegendDot color={RED} label="일별 유출" />
          <LegendDot color={YELLOW} label="누적 보유량" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
          <SummaryCard label="오늘 순유입" value={formatSignedBtc(latestDelta)} tone={flowTone(latestDelta)} />
          <SummaryCard label="기간 순유입" value={formatSignedBtc(periodFlow)} tone={periodTone} />
          <SummaryCard label="총 보유 BTC" value={formatBtcAmount(latest?.totalBtc)} />
          <SummaryCard label="총 AUM" value={formatAum(latest?.totalAumUsd)} />
        </div>
      </div>
    </div>
  );
}

function ChartSkeleton({ overlay = false, height = CHART_HEIGHT_DESKTOP }: { overlay?: boolean; height?: number }) {
  return (
    <div
      className={`${overlay ? "absolute inset-0 z-10" : "relative"} flex items-center justify-center bg-[#0b0e11]`}
      style={{ height }}
      aria-hidden="true"
    >
      <div className="h-full w-full animate-pulse bg-[linear-gradient(90deg,rgba(30,35,41,0.35)_0%,rgba(43,49,57,0.55)_50%,rgba(30,35,41,0.35)_100%)]" />
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[#848e9c]">
      <span className="h-1.5 w-3 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
