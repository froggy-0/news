import type { CSSProperties } from "react";

import type {
  BitcoinSection,
  CryptoIndicator,
  EtfHistoryPoint,
  FearGreedIndex,
  MarketSnapshot,
  TickerItem,
} from "@schema/brief.types";

import { EtfInflowChart } from "@/components/bitcoin/EtfInflowChart";
import { DataState } from "@/components/ui/DataState";
import { RevealSection } from "@/components/ui/RevealSection";

/* ── colour / style helpers ─────────────────────────────────────────────── */

function toneClass(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "text-[var(--accent-green)]";
  if (trend === "down") return "text-[var(--accent-down)]";
  return "text-[#474d57]";
}

function trendColor(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "var(--accent-green)";
  if (trend === "down") return "var(--accent-down)";
  return "rgba(255,255,255,0.36)";
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
      background: `linear-gradient(135deg, rgba(14,203,129,${0.18 + strength * 0.2}), rgba(6,20,18,0.96) 82%)`,
    };
  }
  if (trend === "down") {
    return {
      borderColor: `rgba(246,70,93,${0.24 + strength * 0.22})`,
      background: `linear-gradient(135deg, rgba(246,70,93,${0.18 + strength * 0.2}), rgba(6,20,18,0.96) 82%)`,
    };
  }
  return {
    borderColor: "rgba(255,255,255,0.08)",
    background: "linear-gradient(135deg, rgba(255,255,255,0.05), rgba(10,10,10,0.96) 82%)",
  };
}

/* ── Sparkline ──────────────────────────────────────────────────────────── */

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
    trend === "up" ? "#0ecb81" : trend === "down" ? "#f6465d" : "rgba(255,255,255,0.36)";
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} fill="none" aria-hidden>
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

/* ── Fear & Greed helpers ───────────────────────────────────────────────── */

function fngStage(value: number) {
  if (value <= 20) return { label: "극도 공포", color: "#f6465d", bgColor: "rgba(246,70,93,0.12)" };
  if (value <= 40) return { label: "공포", color: "#f0b90b", bgColor: "rgba(240,185,11,0.10)" };
  if (value <= 60)
    return { label: "중립", color: "rgba(255,255,255,0.55)", bgColor: "rgba(255,255,255,0.05)" };
  if (value <= 80) return { label: "탐욕", color: "#0ecb81", bgColor: "rgba(14,203,129,0.10)" };
  return { label: "극도 탐욕", color: "#0ecb81", bgColor: "rgba(14,203,129,0.16)" };
}

const FNG_SEGMENTS = [
  { max: 20, color: "#f6465d", label: "극공포" },
  { max: 40, color: "#f0b90b", label: "공포" },
  { max: 60, color: "rgba(255,255,255,0.28)", label: "중립" },
  { max: 80, color: "#0ecb81", label: "탐욕" },
  { max: 100, color: "#0ecb81", label: "극탐욕" },
];

/* ── 1. Hero Row — BTC 현물 가격 ────────────────────────────────────────── */

function HeroPrice({ bitcoin }: { bitcoin: BitcoinSection }) {
  const isUp = bitcoin.trend === "up";
  const isDown = bitcoin.trend === "down";

  return (
    <div className="rounded-md border border-[#2b3139] bg-[#1e2329] p-4 md:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span
              className="rounded-sm bg-[#f0b90b] px-1.5 py-0.5 text-[9px] font-bold tracking-wider text-[#1e2329]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              BTC/USD
            </span>
            <span className="text-[10px] font-medium text-[#474d57]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>
              현물
            </span>
          </div>
          {bitcoin.price ? (
            <p
              className="text-[36px] font-bold leading-none tracking-tight text-[#eaecef]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              {bitcoin.price}
            </p>
          ) : (
            <DataState message="이번 집계에서는 현물 가격을 확인하지 못했어요." family="data" minHeight={48} />
          )}
        </div>
        {bitcoin.change && (
          <span
            className={`mt-1 inline-flex items-center gap-1 rounded px-2.5 py-1.5 text-[13px] font-bold ${
              isUp
                ? "bg-[rgba(14,203,129,0.12)] text-[#0ecb81]"
                : isDown
                  ? "bg-[rgba(246,70,93,0.12)] text-[#f6465d]"
                  : "text-[#848e9c]"
            }`}
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {isUp ? "▲" : isDown ? "▼" : ""}
            {bitcoin.change}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── 2. Fear & Greed Gauge (compact) ────────────────────────────────────── */

function FearGreedCompact({ fng }: { fng: FearGreedIndex }) {
  const stage = fngStage(fng.value);
  const markerPct = Math.max(1, Math.min(99, fng.value));

  return (
    <div className="rounded-md border border-[#2b3139] bg-[#1e2329] p-4 md:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span
              className="rounded-sm border border-[#2b3139] px-1.5 py-0.5 text-[9px] font-medium tracking-wider text-[#848e9c]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              FNG INDEX
            </span>
          </div>
          <div className="flex items-end gap-2">
            <p
              className="text-[36px] font-bold leading-none tracking-tight text-[#eaecef]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              {fng.value}
            </p>
            <span className="mb-1 text-[13px] text-[#474d57]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>/100</span>
          </div>
        </div>
        <span
          className="mt-1 rounded px-2.5 py-1.5 text-[12px] font-bold"
          style={{ color: stage.color, background: stage.bgColor, fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          {stage.label}
        </span>
      </div>

      <div className="mt-4 space-y-1.5">
        <div className="relative h-1.5 overflow-visible rounded-full bg-[#2b3139]">
          <div className="absolute inset-0 flex overflow-hidden rounded-full">
            {FNG_SEGMENTS.map((seg, i) => (
              <div
                key={seg.label}
                className="h-full"
                style={{
                  width: "20%",
                  background: seg.color,
                  opacity: fng.value >= (i === 0 ? 0 : FNG_SEGMENTS[i - 1]!.max) ? 0.8 : 0.15,
                  borderRadius:
                    i === 0 ? "9999px 0 0 9999px" : i === FNG_SEGMENTS.length - 1 ? "0 9999px 9999px 0" : "0",
                }}
              />
            ))}
          </div>
          <div
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#eaecef] bg-[#1e2329] shadow-[0_0_8px_rgba(240,185,11,0.4)]"
            style={{ left: `${markerPct}%` }}
          />
        </div>
        <div
          className="flex justify-between text-[9px] uppercase tracking-[0.06em] text-[#474d57]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          {FNG_SEGMENTS.map((seg) => (
            <span key={seg.label}>{seg.label}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── 3. Indicator Grid — 매크로 + 크립토 지표 카드 ──────────────────────── */

function IndicatorCard({ item }: { item: CryptoIndicator }) {
  return (
    <div
      className="h-full rounded-md border border-[#2b3139] bg-[#1e2329] p-3"
      style={compactHeatTone(item.trend, changeMagnitude(item.change), 4)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <p
            className="text-[9px] font-medium uppercase tracking-[0.1em] text-[#474d57]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {item.symbol}
          </p>
          <p className="truncate text-[12px] leading-5 text-[#848e9c]">{item.label}</p>
        </div>
        <div className="shrink-0 text-right">
          <p
            className="text-[14px] font-semibold leading-tight text-[#eaecef]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {item.value ?? "N/A"}
          </p>
          <p
            className={`mt-0.5 text-[11px] font-medium ${toneClass(item.trend)}`}
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {item.change ?? "-"}
          </p>
        </div>
      </div>
      {item.history.length >= 2 && (
        <div className="mt-2 flex justify-end">
          <Sparkline history={item.history} trend={item.trend} width={72} height={24} />
        </div>
      )}
    </div>
  );
}

/* mobile pill for indicators */
function IndicatorPill({ item }: { item: CryptoIndicator }) {
  return (
    <div className="flex min-w-[110px] shrink-0 flex-col gap-1 rounded-md border border-[#2b3139] bg-[#1e2329] px-3 py-2.5 text-center">
      <p
        className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[#474d57]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {item.symbol}
      </p>
      <p
        className="text-[13px] font-semibold text-[#eaecef]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {item.value ?? "N/A"}
      </p>
      <p
        className={`text-[11px] font-medium ${toneClass(item.trend)}`}
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {item.change ?? "-"}
      </p>
    </div>
  );
}

/* ── 4. Market Snapshot — 매크로 지표 (BTC, Gold, US10Y, DXY, VIX) ──── */

function MetricCard({ item }: { item: TickerItem }) {
  return (
    <div
      className="h-full rounded-md border border-[#2b3139] bg-[#1e2329] p-3"
      style={compactHeatTone(item.trend, changeMagnitude(item.change), 3.5)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <span
            className="block text-[9px] font-medium uppercase tracking-[0.1em] text-[#474d57]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {item.symbol}
          </span>
          <p className="truncate text-[12px] leading-5 text-[#848e9c]">{item.label}</p>
        </div>
        <div className="text-right">
          <span
            className="block text-[14px] font-semibold leading-tight text-[#eaecef]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {item.value ?? "N/A"}
          </span>
          <span
            className={`mt-0.5 block text-[11px] font-medium ${toneClass(item.trend)}`}
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            {item.change ?? "-"}
          </span>
        </div>
      </div>
      {item.history.length >= 2 && (
        <div className="mt-2 flex justify-end">
          <Sparkline history={item.history} trend={item.trend} width={72} height={26} />
        </div>
      )}
      {item.isCached ? (
        <p
          className="mt-1.5 text-[9px] text-[#474d57]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          cached
        </p>
      ) : null}
    </div>
  );
}

function MarketStripRow({ item, isLast }: { item: TickerItem; isLast: boolean }) {
  const accentColor =
    item.trend === "up"
      ? "#0ecb81"
      : item.trend === "down"
        ? "#f6465d"
        : "#2b3139";
  return (
    <div
      className={`grid items-center gap-3 px-4 py-3 ${!isLast ? "border-b border-[#2b3139]" : ""}`}
      style={{ gridTemplateColumns: "1fr 64px auto" }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className="h-8 w-[2px] shrink-0 rounded-full"
            style={{ background: accentColor }}
          />
          <div className="min-w-0">
            <p
              className="text-[12px] font-semibold leading-tight text-[#eaecef]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              {item.symbol}
            </p>
            <p className="mt-0.5 truncate text-[11px] text-[#474d57]">{item.label}</p>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center">
        <Sparkline history={item.history} trend={item.trend} width={56} height={24} />
      </div>
      <div className="text-right">
        <p
          className="text-[12px] font-semibold leading-tight text-[#eaecef]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          {item.value ?? "N/A"}
        </p>
        <p
          className={`mt-0.5 text-[11px] font-medium ${toneClass(item.trend)}`}
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          {item.change ?? "-"}
        </p>
      </div>
    </div>
  );
}

/* ── 5. ETF Detail ──────────────────────────────────────────────────────── */

function EtfStatCallout({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-md border border-[#2b3139] bg-[#161a1e] px-4 py-3">
      <p
        className="text-[9px] font-medium uppercase tracking-[0.14em] text-[#474d57]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {label}
      </p>
      <p
        className="mt-1.5 text-[15px] font-semibold text-[#eaecef]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {value ?? "N/A"}
      </p>
    </div>
  );
}

function EtfIssuerRow({
  name,
  holding,
  aum,
  sourceUrl,
  isFirst,
}: {
  name: string;
  holding: string | null;
  aum: string | null;
  sourceUrl: string;
  isFirst: boolean;
}) {
  const inner = (
    <>
      <div className="flex items-center gap-2">
        <span
          className="rounded-sm border border-[#2b3139] bg-[#1e2329] px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-[#848e9c]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          {name}
        </span>
      </div>
      <p
        className="text-[12px] text-[#848e9c]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {holding ?? "N/A"}
      </p>
      <p
        className="text-right text-[12px] text-[#848e9c]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        {aum ?? "N/A"}
      </p>
    </>
  );
  const rowClass = `grid items-center gap-3 px-4 py-3 transition ${!isFirst ? "border-t border-[#2b3139]" : ""}`;
  const gridStyle = { gridTemplateColumns: "1fr 1fr 1fr" };

  return sourceUrl ? (
    <a
      href={sourceUrl}
      target="_blank"
      rel="noreferrer"
      className={`${rowClass} hover:bg-[#2b3139]/40`}
      style={gridStyle}
    >
      {inner}
    </a>
  ) : (
    <div className={rowClass} style={gridStyle}>
      {inner}
    </div>
  );
}

function EtfDetail({
  etf,
  etfHistory,
}: {
  etf: BitcoinSection["etf"];
  etfHistory: EtfHistoryPoint[] | null;
}) {
  if (!etf && (!etfHistory || etfHistory.length === 0)) return null;

  return (
    <div className="md:rounded-md md:border md:border-[#2b3139] md:bg-[#1e2329] md:p-5">
      <div className="flex flex-col gap-4 px-4 pb-3 pt-5 md:flex-row md:items-start md:justify-between md:p-0 md:pb-4">
        <div className="space-y-0.5">
          <p
            className="text-[10px] font-medium uppercase tracking-[0.12em] text-[#474d57]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            BTC ETF 스냅샷
          </p>
          <p className="text-[13px] text-[#848e9c]">총 보유량·AUM과 순유입 흐름</p>
        </div>
        {etf && (
          <div className="grid grid-cols-2 gap-2.5 md:min-w-[280px]">
            <EtfStatCallout label="총 보유량" value={etf.totalHolding} />
            <EtfStatCallout label="총 AUM" value={etf.totalAum} />
          </div>
        )}
      </div>

      {etfHistory && etfHistory.length > 1 && <EtfInflowChart history={etfHistory} />}

      {etf && etf.issuers.length > 0 && (
        <div className="mx-4 mt-4 overflow-hidden rounded-md border border-[#2b3139] bg-[#161a1e] md:mx-0">
          <div
            className="grid border-b border-[#2b3139] px-4 py-2"
            style={{ gridTemplateColumns: "1fr 1fr 1fr" }}
          >
            <p
              className="text-[9px] uppercase tracking-[0.14em] text-[#474d57]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              운용사
            </p>
            <p
              className="text-[9px] uppercase tracking-[0.14em] text-[#474d57]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              보유량
            </p>
            <p
              className="text-right text-[9px] uppercase tracking-[0.14em] text-[#474d57]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              AUM
            </p>
          </div>
          {etf.issuers.map((issuer, i) => (
            <EtfIssuerRow
              key={issuer.name}
              name={issuer.name}
              holding={issuer.holding}
              aum={issuer.aum}
              sourceUrl={issuer.sourceUrl}
              isFirst={i === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── animation delays ───────────────────────────────────────────────────── */

function metricDelay(i: number): string {
  return `${140 + i * 160}ms`;
}

function indicatorDelay(i: number): string {
  return `${180 + i * 140}ms`;
}

/* ── Main export ────────────────────────────────────────────────────────── */

export function CryptoPulseBoard({
  snapshot,
  indicators,
  bitcoin,
  etfHistory,
}: {
  snapshot: MarketSnapshot;
  indicators: CryptoIndicator[];
  bitcoin: BitcoinSection;
  etfHistory: EtfHistoryPoint[] | null;
}) {
  return (
    <RevealSection className="border-b border-[#2b3139] px-4 py-10 md:px-6" revealAt={0.88} delayMs={60}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        {/* ── Section header ─────────────────────────────────────────── */}
        <div className="flex items-center justify-between border-b border-[#2b3139] pb-4">
          <div className="flex items-center gap-3">
            <span
              className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#eaecef]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              크립토 흐름
            </span>
            <span className="h-3.5 w-px bg-[#2b3139]" />
            <span
              className="text-[10px] uppercase tracking-[0.1em] text-[#474d57]"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Market Overview
            </span>
          </div>
          <div
            className="flex items-center gap-3 text-[9px] uppercase tracking-[0.1em] text-[#474d57]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#0ecb81]" />
              상승
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#f6465d]" />
              하락
            </span>
          </div>
        </div>

        {/* ── 1. Hero Row: BTC price + F&G ───────────────────────────── */}
        <div className="grid gap-3 md:grid-cols-2">
          <HeroPrice bitcoin={bitcoin} />
          {bitcoin.fearGreedIndex ? (
            <FearGreedCompact fng={bitcoin.fearGreedIndex} />
          ) : (
            <div className="rounded-md border border-[#2b3139] bg-[#1e2329] p-5">
              <DataState
                title="공포·탐욕"
                message="이번 집계에서는 공포탐욕지수를 확인하지 못했어요."
                family="data"
                minHeight={100}
              />
            </div>
          )}
        </div>

        {/* ── 2. Market Reference Snapshot ────────────────────────────── */}
        {snapshot.items.length > 0 ? (
          <>
            {/* mobile: strip rows */}
            <div className="overflow-hidden rounded-md border border-[#2b3139] bg-[#1e2329] md:hidden">
              {snapshot.items.map((item, i) => (
                <MarketStripRow key={item.symbol} item={item} isLast={i === snapshot.items.length - 1} />
              ))}
            </div>
            {/* desktop: grid */}
            <div className="hidden gap-2.5 md:grid md:grid-cols-3 lg:grid-cols-5">
              {snapshot.items.map((item, i) => (
                <div
                  key={item.symbol}
                  style={{ animationDelay: metricDelay(i) }}
                >
                  <MetricCard item={item} />
                </div>
              ))}
            </div>
          </>
        ) : (
          <DataState
            title="시장 참고 지표"
            message="이번 집계에서는 시장 참고 지표를 확인하지 못했어요."
            family="data"
            minHeight={120}
          />
        )}

        {/* ── 3. Crypto Indicators ───────────────────────────────────── */}
        {indicators.length > 0 && (
          <div>
            <div className="mb-3 flex items-center gap-3 border-b border-[#2b3139] pb-3">
              <span
                className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#eaecef]"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                핵심 지표
              </span>
              <span
                className="text-[10px] text-[#474d57]"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                심리 · ETF · 달러 · 금리
              </span>
            </div>

            {/* mobile: horizontal scroll pills */}
            <div className="flex gap-2 overflow-x-auto pb-1 md:hidden">
              {indicators.map((ind, i) => (
                <div key={ind.symbol} style={{ animationDelay: indicatorDelay(i) }}>
                  <IndicatorPill item={ind} />
                </div>
              ))}
            </div>
            {/* desktop: grid */}
            <div className="hidden gap-2.5 md:grid md:grid-cols-3 xl:grid-cols-5">
              {indicators.map((ind, i) => (
                <div
                  key={ind.symbol}
                  style={{ animationDelay: indicatorDelay(i) }}
                >
                  <IndicatorCard item={ind} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── 4. ETF Detail — breakout on mobile for full-width chart ── */}
        <div className="-mx-4 md:mx-0">
          <EtfDetail etf={bitcoin.etf} etfHistory={etfHistory} />
        </div>
      </div>
    </RevealSection>
  );
}
