import React from "react";

import type { BitcoinSection, FearGreedIndex } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { RevealSection } from "@/components/ui/RevealSection";

// ─── helpers ─────────────────────────────────────────────────────────────────

function fngStage(value: number): {
  label: string;
  color: string;
  bgColor: string;
} {
  if (value <= 20) return { label: "극도 공포", color: "#f6465d", bgColor: "rgba(246,70,93,0.12)" };
  if (value <= 40) return { label: "공포", color: "#f0b90b", bgColor: "rgba(240,185,11,0.10)" };
  if (value <= 60) return { label: "중립", color: "rgba(255,255,255,0.55)", bgColor: "rgba(255,255,255,0.05)" };
  if (value <= 80) return { label: "탐욕", color: "#0ecb81", bgColor: "rgba(14,203,129,0.10)" };
  return { label: "극도 탐욕", color: "#0ecb81", bgColor: "rgba(14,203,129,0.16)" };
}

function trendColor(trend: "up" | "down" | "neutral" | null): string {
  if (trend === "up") return "var(--accent-green)";
  if (trend === "down") return "var(--accent-down)";
  return "rgba(255,255,255,0.36)";
}

// ─── BTC 현물 카드 ────────────────────────────────────────────────────────────

function BitcoinPriceCard({
  price,
  change,
  trend,
}: {
  price: string | null;
  change: string | null;
  trend: "up" | "down" | "neutral" | null;
}) {
  const borderLeft = trendColor(trend);
  const changeColor =
    trend === "up"
      ? "text-[var(--accent-green)]"
      : trend === "down"
        ? "text-[var(--accent-down)]"
        : "text-white/46";

  return (
    <div
      className="section-shell card-family-data relative overflow-hidden rounded-[var(--card-radius-data)] p-6"
      style={{ borderLeftColor: borderLeft, borderLeftWidth: "3px" }}
    >
      {/* 헤더 */}
      <div className="flex items-center justify-between gap-3">
        <p className="section-title">비트코인 현물</p>
        {change && (
          <span
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-[11px] font-semibold ${changeColor}`}
            style={{
              borderColor: `${borderLeft}40`,
              background: `${borderLeft}12`,
            }}
          >
            {trend === "up" ? "▲" : trend === "down" ? "▼" : ""}
            {change}
          </span>
        )}
      </div>

      {/* 가격 */}
      {price ? (
        <p className="numeric-display mt-5 text-white">{price}</p>
      ) : (
        <div className="mt-5">
          <DataState message="이번 집계에서는 비트코인 현물을 확인하지 못했어요." />
        </div>
      )}

      {/* 구분선 + 설명 */}
      <div className="mt-6 border-t border-white/8 pt-5">
        <p className="text-[13px] leading-6 text-white/46">
          가격만으로는 방향을 단정하지 않고, 위험 선호와 ETF 수급의 동시 변화를 함께 해석합니다.
        </p>
      </div>
    </div>
  );
}

// ─── 공포탐욕 카드 ────────────────────────────────────────────────────────────

const FNG_SEGMENTS = [
  { max: 20, color: "#f6465d", label: "극공포" },
  { max: 40, color: "#f0b90b", label: "공포" },
  { max: 60, color: "rgba(255,255,255,0.28)", label: "중립" },
  { max: 80, color: "#0ecb81", label: "탐욕" },
  { max: 100, color: "#0ecb81", label: "극탐욕" },
];

function FearGreedGauge({ fng }: { fng: FearGreedIndex }) {
  const stage = fngStage(fng.value);
  const markerPct = Math.max(1, Math.min(99, fng.value));

  return (
    <div className="mt-5 space-y-4">
      {/* 숫자 + 단계 뱃지 */}
      <div className="flex items-end gap-3">
        <p className="numeric-display text-white">{fng.value}</p>
        <div className="mb-1 flex flex-col items-start gap-1">
          <span className="numeric-sm text-white/32">/100</span>
          <span
            className="rounded-full px-2.5 py-0.5 font-mono text-[11px] font-semibold"
            style={{ color: stage.color, background: stage.bgColor }}
          >
            {stage.label}
          </span>
        </div>
      </div>

      {/* 5구간 그라디언트 게이지 */}
      <div className="space-y-1.5">
        <div className="relative h-2 overflow-visible rounded-full bg-white/8">
          {/* 5구간 색상 바 */}
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

          {/* 현재 위치 마커 */}
          <div
            className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[#181a20] shadow-[0_0_8px_rgba(255,255,255,0.4)]"
            style={{ left: `${markerPct}%` }}
          />
        </div>

        {/* 구간 레이블 */}
        <div className="flex justify-between font-mono text-[9px] uppercase tracking-[0.08em] text-white/24">
          {FNG_SEGMENTS.map((seg) => (
            <span key={seg.label}>{seg.label}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function FearGreedCard({ fearGreedIndex }: { fearGreedIndex: FearGreedIndex | null }) {
  return (
    <div className="section-shell card-family-data rounded-[var(--card-radius-data)] p-6">
      <p className="section-title">공포탐욕지수</p>
      {fearGreedIndex ? (
        <FearGreedGauge fng={fearGreedIndex} />
      ) : (
        <div className="mt-5">
          <DataState message="이번 집계에서는 공포탐욕지수를 확인하지 못했어요." />
        </div>
      )}
    </div>
  );
}

// ─── ETF 스냅샷 카드 ──────────────────────────────────────────────────────────

function EtfStatCallout({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-xl border border-white/8 bg-black/30 px-4 py-3.5">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/34">{label}</p>
      <p className="numeric-md mt-2 font-semibold text-white">{value ?? "N/A"}</p>
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
      {/* 티커 배지 */}
      <div className="flex items-center gap-2">
        <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-white/72">
          {name}
        </span>
      </div>
      <p className="numeric-sm text-white/70">{holding ?? "N/A"}</p>
      <p className="numeric-sm text-right text-white/70">{aum ?? "N/A"}</p>
    </>
  );

  const rowClass = `grid items-center gap-3 px-4 py-3.5 transition ${
    !isFirst ? "border-t border-white/6" : ""
  }`;
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

function EtfSnapshotCard({ etf }: { etf: BitcoinSection["etf"] }) {
  return (
    <div className="section-shell card-family-data rounded-[var(--card-radius-data)] p-6">
      {/* 헤더 */}
      <div className="border-b border-white/8 pb-5">
        <p className="section-title">공식 ETF 스냅샷</p>
        <p className="mt-2 text-[13px] leading-6 text-white/46">
          공식 페이지에서 바로 확인되는 총 보유량과 AUM만 표시합니다.
        </p>

        {/* stat-callout 2개 */}
        {etf && (
          <div className="mt-4 grid grid-cols-2 gap-3">
            <EtfStatCallout label="총 보유량" value={etf.totalHolding} />
            <EtfStatCallout label="총 AUM" value={etf.totalAum} />
          </div>
        )}
      </div>

      {/* 발행사 테이블 */}
      {etf ? (
        etf.issuers.length > 0 ? (
          <div className="mt-5 overflow-hidden rounded-xl border border-white/8 bg-black/20">
            {/* 테이블 헤더 */}
            <div
              className="grid border-b border-white/8 px-4 py-2.5"
              style={{ gridTemplateColumns: "1fr 1fr 1fr" }}
            >
              <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/28">운용사</p>
              <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/28">보유량</p>
              <p className="text-right font-mono text-[9px] uppercase tracking-[0.14em] text-white/28">AUM</p>
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
        ) : (
          <div className="mt-5">
            <DataState message="이번 집계에서는 ETF 발행사별 보유 현황을 확인하지 못했어요." />
          </div>
        )
      ) : (
        <div className="mt-5">
          <DataState message="이번 집계에서는 공식 ETF 보유 현황을 확인하지 못했어요." />
        </div>
      )}
    </div>
  );
}

// ─── 메인 ─────────────────────────────────────────────────────────────────────

export function BitcoinPanel({ bitcoin }: { bitcoin: BitcoinSection }) {
  return (
    <RevealSection className="border-b border-white/10 px-6 py-16" revealAt={0.84} delayMs={80}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">

        {/* 섹션 헤더 */}
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <p className="section-title">비트코인과 ETF</p>
            <p className="max-w-2xl text-[0.95rem] leading-7 text-[var(--text-secondary)]">
              현물 가격, 투자 심리, 공식 ETF 핵심 수치를 압축해서 함께 봅니다.
            </p>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/46">
            시세와 심리만 따로 보지 않고, 실제 ETF 집행 강도와 함께 읽도록 구성합니다.
          </p>
        </div>

        {/* 상단: 현물 + 공포탐욕 (2열) */}
        <div className="grid gap-4 sm:grid-cols-2">
          <BitcoinPriceCard
            price={bitcoin.price}
            change={bitcoin.change}
            trend={bitcoin.trend}
          />
          <FearGreedCard fearGreedIndex={bitcoin.fearGreedIndex} />
        </div>

        {/* 하단: ETF 스냅샷 (full width) */}
        <EtfSnapshotCard etf={bitcoin.etf} />

      </div>
    </RevealSection>
  );
}
