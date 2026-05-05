import type { CSSProperties } from "react";

import type {
  BitcoinSection,
  CryptoIndicator,
  FearGreedIndex,
  MarketSnapshot,
  TickerItem,
} from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { RevealSection } from "@/components/ui/RevealSection";

/* ── colour / style helpers ─────────────────────────────────────────────── */

function toneClass(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "text-[var(--accent-green)]";
  if (trend === "down") return "text-[var(--accent-down)]";
  return "text-white/55";
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
  const borderLeft = trendColor(bitcoin.trend);
  const changeColor =
    bitcoin.trend === "up"
      ? "text-[var(--accent-green)]"
      : bitcoin.trend === "down"
        ? "text-[var(--accent-down)]"
        : "text-white/46";

  return (
    <div
      className="rounded-xl border border-white/8 bg-black/20 p-5 md:p-6"
      style={{ borderLeftColor: borderLeft, borderLeftWidth: "3px" }}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <p className="label-meta text-white/42">BTC / USD</p>
          {bitcoin.price ? (
            <p className="numeric-display text-white">{bitcoin.price}</p>
          ) : (
            <DataState message="이번 집계에서는 현물 가격을 확인하지 못했어요." family="data" minHeight={48} />
          )}
        </div>
        {bitcoin.change && (
          <span
            className={`inline-flex w-fit items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[12px] font-semibold ${changeColor}`}
            style={{ borderColor: `${borderLeft}40`, background: `${borderLeft}12` }}
          >
            {bitcoin.trend === "up" ? "▲" : bitcoin.trend === "down" ? "▼" : ""}
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
    <div className="rounded-xl border border-white/8 bg-black/20 p-5 md:p-6">
      <p className="label-meta text-white/42">공포·탐욕</p>

      <div className="mt-3 flex items-end gap-2.5">
        <p className="text-[32px] font-bold leading-none tracking-tight text-white" style={{ fontFamily: "var(--numeric-type)" }}>
          {fng.value}
        </p>
        <div className="mb-0.5 flex flex-col gap-0.5">
          <span className="numeric-sm text-white/28">/100</span>
          <span
            className="rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold"
            style={{ color: stage.color, background: stage.bgColor }}
          >
            {stage.label}
          </span>
        </div>
      </div>

      {/* gauge bar */}
      <div className="mt-4 space-y-1">
        <div className="relative h-1.5 overflow-visible rounded-full bg-white/8">
          <div className="absolute inset-0 flex overflow-hidden rounded-full">
            {FNG_SEGMENTS.map((seg, i) => (
              <div
                key={seg.label}
                className="h-full"
                style={{
                  width: "20%",
                  background: seg.color,
                  opacity: fng.value >= (i === 0 ? 0 : FNG_SEGMENTS[i - 1]!.max) ? 0.72 : 0.18,
                  borderRadius:
                    i === 0
                      ? "9999px 0 0 9999px"
                      : i === FNG_SEGMENTS.length - 1
                        ? "0 9999px 9999px 0"
                        : "0",
                }}
              />
            ))}
          </div>
          <div
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[#181a20] shadow-[0_0_6px_rgba(255,255,255,0.35)]"
            style={{ left: `${markerPct}%` }}
          />
        </div>
        <div className="flex justify-between font-mono text-[8px] uppercase tracking-[0.06em] text-white/20">
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
      className="card-family-data h-full"
      style={compactHeatTone(item.trend, changeMagnitude(item.change), 4)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <p className="label-meta text-white/42">{item.symbol}</p>
          <p className="truncate text-[13px] leading-5 text-white/78">{item.label}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="numeric-md font-semibold text-white">{item.value ?? "N/A"}</p>
          <p className={`mt-0.5 text-[12px] ${toneClass(item.trend)}`}>{item.change ?? "-"}</p>
        </div>
      </div>
      {item.history.length >= 2 && (
        <div className="mt-2.5 flex justify-end">
          <Sparkline history={item.history} trend={item.trend} width={72} height={26} />
        </div>
      )}
    </div>
  );
}

/* mobile pill for indicators */
function IndicatorPill({ item }: { item: CryptoIndicator }) {
  return (
    <div className="flex min-w-[124px] shrink-0 flex-col gap-1 rounded-xl border border-white/8 bg-white/[0.025] px-3 py-2.5 text-center">
      <p className="numeric-sm font-semibold text-white">{item.symbol}</p>
      <p className="numeric-sm text-white/80">{item.value ?? "N/A"}</p>
      <p className={`text-[11px] font-medium ${toneClass(item.trend)}`}>{item.change ?? "-"}</p>
    </div>
  );
}

/* ── 4. Market Snapshot — 매크로 지표 (BTC, Gold, US10Y, DXY, VIX) ──── */

function MetricCard({ item }: { item: TickerItem }) {
  return (
    <div
      className="card-family-data h-full"
      style={compactHeatTone(item.trend, changeMagnitude(item.change), 3.5)}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <span className="label-meta truncate text-white/46">{item.symbol}</span>
          <p className="truncate text-[13px] leading-5 text-white/78">{item.label}</p>
        </div>
        <div className="text-right">
          <span className="numeric-md block leading-tight text-white">{item.value ?? "N/A"}</span>
          <div className={`mt-1 text-[12px] ${toneClass(item.trend)}`}>
            <span>{item.change ?? "-"}</span>
          </div>
        </div>
      </div>
      {item.history.length >= 2 && (
        <div className="mt-3 flex justify-end">
          <Sparkline history={item.history} trend={item.trend} width={72} height={28} />
        </div>
      )}
      {item.isCached ? <p className="label-meta mt-2 text-white/28">cached</p> : null}
    </div>
  );
}

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
      <div className="flex items-center justify-center">
        <Sparkline history={item.history} trend={item.trend} width={64} height={26} />
      </div>
      <div className="text-right">
        <p className="numeric-sm font-semibold leading-tight text-white">{item.value ?? "N/A"}</p>
        <p className={`mt-0.5 text-[11px] font-medium ${toneClass(item.trend)}`}>
          {item.change ?? "-"}
          {item.isCached ? <span className="ml-1 text-white/24">·</span> : null}
        </p>
      </div>
    </div>
  );
}

/* ── 5. ETF Detail ──────────────────────────────────────────────────────── */

function EtfStatCallout({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-xl border border-white/8 bg-black/30 px-4 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/34">{label}</p>
      <p className="numeric-md mt-1.5 font-semibold text-white">{value ?? "N/A"}</p>
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
        <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-white/72">
          {name}
        </span>
      </div>
      <p className="numeric-sm text-white/70">{holding ?? "N/A"}</p>
      <p className="numeric-sm text-right text-white/70">{aum ?? "N/A"}</p>
    </>
  );
  const rowClass = `grid items-center gap-3 px-4 py-3 transition ${!isFirst ? "border-t border-white/6" : ""}`;
  const gridStyle = { gridTemplateColumns: "1fr 1fr 1fr" };

  return sourceUrl ? (
    <a
      href={sourceUrl}
      target="_blank"
      rel="noreferrer"
      className={`${rowClass} hover:bg-white/[0.04]`}
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

function EtfDetail({ etf }: { etf: BitcoinSection["etf"] }) {
  if (!etf) return null;

  return (
    <div className="rounded-xl border border-white/8 bg-black/20 p-5 md:p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <p className="label-meta text-white/42">공식 ETF 스냅샷</p>
          <p className="text-[13px] leading-6 text-white/46">
            공식 페이지에서 확인되는 총 보유량과 AUM
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2.5 md:min-w-[280px]">
          <EtfStatCallout label="총 보유량" value={etf.totalHolding} />
          <EtfStatCallout label="총 AUM" value={etf.totalAum} />
        </div>
      </div>

      {etf.issuers.length > 0 && (
        <div className="mt-5 overflow-hidden rounded-xl border border-white/8 bg-black/20">
          <div
            className="grid border-b border-white/8 px-4 py-2"
            style={{ gridTemplateColumns: "1fr 1fr 1fr" }}
          >
            <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/28">운용사</p>
            <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/28">보유량</p>
            <p className="text-right font-mono text-[9px] uppercase tracking-[0.14em] text-white/28">
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
}: {
  snapshot: MarketSnapshot;
  indicators: CryptoIndicator[];
  bitcoin: BitcoinSection;
}) {
  return (
    <RevealSection className="border-b border-white/10 px-6 py-20" revealAt={0.88} delayMs={60}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        {/* ── Section header ─────────────────────────────────────────── */}
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="section-title">크립토 흐름</h2>
            <p className="eyebrow">흐름 보기</p>
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

        {/* ── 1. Hero Row: BTC price + F&G ───────────────────────────── */}
        <div className="grid gap-4 md:grid-cols-2">
          <HeroPrice bitcoin={bitcoin} />
          {bitcoin.fearGreedIndex ? (
            <FearGreedCompact fng={bitcoin.fearGreedIndex} />
          ) : (
            <div className="rounded-xl border border-white/8 bg-black/20 p-5">
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
            <div className="overflow-hidden rounded-2xl border border-white/8 bg-black/24 md:hidden">
              {snapshot.items.map((item, i) => (
                <MarketStripRow key={item.symbol} item={item} isLast={i === snapshot.items.length - 1} />
              ))}
            </div>
            {/* desktop: grid */}
            <div className="hidden gap-3 md:grid md:grid-cols-3 lg:grid-cols-5">
              {snapshot.items.map((item, i) => (
                <div
                  key={item.symbol}
                  className="card-data market-heat-card"
                  data-trend={item.trend ?? "neutral"}
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
            <div className="mb-4">
              <p className="section-title">핵심 지표</p>
              <p className="mt-1 text-[13px] leading-6 text-[var(--text-secondary)]">
                투자 심리, ETF 자금 흐름, 달러와 금리 변화를 함께 확인합니다.
              </p>
            </div>

            {/* mobile: horizontal scroll pills */}
            <div className="flex gap-2.5 overflow-x-auto pb-1 md:hidden">
              {indicators.map((ind, i) => (
                <div key={ind.symbol} style={{ animationDelay: indicatorDelay(i) }}>
                  <IndicatorPill item={ind} />
                </div>
              ))}
            </div>
            {/* desktop: grid */}
            <div className="hidden gap-3 md:grid md:grid-cols-3 xl:grid-cols-5">
              {indicators.map((ind, i) => (
                <div
                  key={ind.symbol}
                  className="card-data market-heat-card"
                  data-trend={ind.trend ?? "neutral"}
                  style={{ animationDelay: indicatorDelay(i) }}
                >
                  <IndicatorCard item={ind} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── 4. ETF Detail ──────────────────────────────────────────── */}
        <EtfDetail etf={bitcoin.etf} />
      </div>
    </RevealSection>
  );
}
