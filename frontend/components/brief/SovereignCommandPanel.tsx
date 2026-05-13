import React from "react";
import { BarChart2, Activity, ShieldCheck, TrendingUp } from "lucide-react";

import type { RiskOverlay, SovereignIndex } from "@schema/brief.types";

/* ── zone ────────────────────────────────────────────────────────────────── */

const ZONE_CFG = {
  bull:    { color: "#10b981", label: "강세 구간", borderColor: "rgba(16,185,129,0.22)" },
  neutral: { color: "#64748b", label: "중립 구간", borderColor: "rgba(100,116,139,0.22)" },
  bear:    { color: "#ef4444", label: "약세 구간", borderColor: "rgba(246,70,93,0.28)" },
} as const;

/* ── regime ──────────────────────────────────────────────────────────────── */

const REGIME_CFG: Record<string, { label: string; color: string }> = {
  BullQuiet:    { label: "안정 상승", color: "#10b981" },
  BullHeated:   { label: "과열 상승", color: "#f0b90b" },
  BearPanic:    { label: "공포 하락", color: "#ef4444" },
  Choppy:       { label: "방향 불명", color: "#f0b90b" },
  Transitional: { label: "전환 구간", color: "rgba(255,255,255,0.76)" },
};

const VOL_LABELS: Record<string, string> = { Low: "낮음", Mid: "보통", High: "높음" };
const VOL_TREND_LABELS: Record<string, string> = {
  rising: "↑ 상승 중",
  falling: "↓ 하락 중",
  stable: "→ 안정",
};

const CONFIDENCE_CFG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  HIGH:   { label: "강함", color: "#10b981", bg: "rgba(16,185,129,0.10)",      border: "rgba(16,185,129,0.30)" },
  MEDIUM: { label: "보통", color: "#f0b90b", bg: "rgba(240,185,11,0.10)",      border: "rgba(240,185,11,0.28)" },
  LOW:    { label: "낮음", color: "rgba(255,255,255,0.52)", bg: "rgba(255,255,255,0.05)", border: "rgba(255,255,255,0.12)" },
  NONE:   { label: "대기", color: "rgba(255,255,255,0.38)", bg: "rgba(255,255,255,0.04)", border: "rgba(255,255,255,0.10)" },
};

/* ── gauge ───────────────────────────────────────────────────────────────── */

function GaugeBar({ score, zone }: { score: number; zone: SovereignIndex["zone"] }) {
  const pct = Math.min(100, Math.max(0, score));
  const color = ZONE_CFG[zone].color;
  return (
    <div className="mt-5">
      <div className="mb-1.5 flex justify-between font-mono text-[9px] text-white/26">
        <span>0</span><span>50</span><span>100</span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-white/[0.07]">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <div className="relative mt-1 flex font-mono text-[9px] text-white/22">
        <div style={{ width: "30%" }} className="border-r border-white/10 pr-1 text-right">30</div>
        <div style={{ width: "40%" }} className="border-r border-white/10" />
        <div style={{ width: "30%" }} className="pl-1">70</div>
      </div>
    </div>
  );
}

function ZoneLegend({ zone }: { zone: SovereignIndex["zone"] }) {
  const zones = [
    { key: "bull" as const,    color: "#10b981", label: "강세", range: "70 ↑" },
    { key: "neutral" as const, color: "#64748b", label: "중립", range: "30 – 70" },
    { key: "bear" as const,    color: "#ef4444", label: "약세", range: "↓ 30" },
  ];
  return (
    <div className="mt-4 flex flex-col gap-2">
      {zones.map(({ key, color, label, range }) => {
        const active = key === zone;
        return (
          <div key={key} className="flex items-center gap-2.5">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: color, opacity: active ? 1 : 0.26 }}
            />
            <span
              className="font-mono text-[10px] uppercase tracking-[0.12em]"
              style={{ color: active ? color : "rgba(255,255,255,0.24)", fontWeight: active ? 700 : 400 }}
            >
              {range}
            </span>
            <span
              className="text-xs"
              style={{ color: active ? "rgba(255,255,255,0.86)" : "rgba(255,255,255,0.24)", fontWeight: active ? 600 : 400 }}
            >
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ── LEFT: Sovereign Index ───────────────────────────────────────────────── */

function IndexPanel({ si }: { si: SovereignIndex }) {
  const cfg = ZONE_CFG[si.zone];
  const isOos = si.todayScoreMethod === "oos_expanding";
  const isDegraded = si.qualityStatus !== "ok";

  return (
    <div className="bg-[#0b0a08]/95 p-5 md:p-7">
      {/* Title */}
      <div className="flex items-center gap-3">
        <span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border bg-white/[0.03]"
          style={{ borderColor: "rgba(0,255,255,0.22)", color: "#00ffff" }}
        >
          <BarChart2 className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.22em]" style={{ color: "#00ffff" }}>
            Sovereign Index
          </p>
          <p className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.14em] text-white/36">
            BTC 시장 복합 지표
          </p>
        </div>
      </div>

      {/* Score */}
      <div className="mt-5 flex items-baseline gap-3">
        <span
          className="font-mono text-[68px] font-bold leading-none tabular-nums"
          style={{ color: cfg.color, letterSpacing: "-0.03em" }}
        >
          {Math.round(si.score)}
        </span>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-sm text-white/36">/ 100</span>
          <span className="text-sm font-bold" style={{ color: cfg.color }}>
            {si.labelKo}
          </span>
          {isOos && (
            <span className="rounded border border-[rgba(0,255,255,0.18)] bg-[rgba(0,255,255,0.05)] px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-[0.14em] text-[rgba(0,255,255,0.48)]">
              실전 검증
            </span>
          )}
        </div>
      </div>

      <GaugeBar score={si.score} zone={si.zone} />
      <ZoneLegend zone={si.zone} />

      {/* 예측 정확도 (T+7 hit rate) */}
      {si.trackAWfAvgHitRate != null && (
        <div className="mt-5 rounded-md border border-white/8 bg-white/[0.025] px-3 py-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/32">예측 정확도</p>
              <p className="mt-0.5 font-mono text-[9px] text-white/24">7일 방향 기준</p>
            </div>
            <div className="text-right">
              <span className="font-mono text-[22px] font-bold leading-none text-white/70">
                {(si.trackAWfAvgHitRate * 100).toFixed(1)}%
              </span>
              {si.trackAWfFolds != null && (
                <p className="mt-0.5 font-mono text-[9px] text-white/26">검증 {si.trackAWfFolds}회</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 지수 구성 신호 (PC interpretation) */}
      {si.pcInterpretation && (
        <div className="mt-3 border-l-2 border-[rgba(0,255,255,0.18)] pl-3">
          <p className="font-mono text-[8px] uppercase tracking-[0.14em] text-white/24">지수 구성 신호</p>
          <p className="mt-1 font-mono text-[9px] leading-relaxed text-white/40">
            {si.pcInterpretation}
          </p>
        </div>
      )}

      {isDegraded && (
        <p className="mt-4 text-[11px] leading-relaxed text-white/32">
          ⚠ 일부 데이터 누락으로 지수 신뢰도가 낮을 수 있어요
        </p>
      )}
    </div>
  );
}

/* ── RIGHT: Sovereign State ──────────────────────────────────────────────── */

function StatePanel({ overlay }: { overlay: RiskOverlay }) {
  const regime = REGIME_CFG[overlay.regimeState] ?? { label: overlay.regimeState, color: "rgba(255,255,255,0.76)" };
  const confidence = CONFIDENCE_CFG[overlay.signalConfidence ?? "NONE"] ?? CONFIDENCE_CFG.NONE;
  const volLabel = VOL_LABELS[overlay.volLevel] ?? overlay.volLevel;
  const volTrend = VOL_TREND_LABELS[overlay.volTrend] ?? overlay.volTrend;
  const reasons = overlay.signalReasonLabels.slice(0, 3);
  const isPromoted = overlay.overlayGateDecision === "promote";

  return (
    <div className="bg-[#0b0a08]/95 p-5 md:p-7">
      {/* Title */}
      <div className="flex items-center gap-3">
        <span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-white/12 bg-white/[0.03] text-white/56"
        >
          <Activity className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.22em] text-white/68">
            Sovereign State
          </p>
          <p className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.14em] text-white/32">
            시장 국면 · 실시간 추적
          </p>
        </div>
      </div>

      {/* Regime — main value */}
      <div className="mt-5">
        <p
          className="text-[34px] font-black leading-none"
          style={{ color: regime.color }}
        >
          {regime.label}
        </p>
        <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-white/28">
          {overlay.regimeState}
        </p>
        {overlay.regimeDescription && (
          <p className="mt-3 text-sm leading-6 text-white/52">{overlay.regimeDescription}</p>
        )}
      </div>

      {/* Vol */}
      <div className="mt-5 grid grid-cols-2 gap-2">
        <div className="rounded-md border border-white/8 bg-white/[0.025] px-3 py-2.5">
          <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/32">변동성</p>
          <p className="mt-1 text-[15px] font-bold text-white/82">{volLabel}</p>
        </div>
        <div className="rounded-md border border-white/8 bg-white/[0.025] px-3 py-2.5">
          <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/32">추세</p>
          <p className="mt-1 text-[13px] font-bold text-white/82">{volTrend}</p>
        </div>
      </div>

      {/* Signal confidence */}
      <div
        className="mt-3 flex items-center justify-between rounded-md border px-3 py-2.5"
        style={{ borderColor: confidence.border, background: confidence.bg }}
      >
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-3.5 w-3.5" style={{ color: confidence.color }} aria-hidden />
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/36">오늘의 신호</span>
        </div>
        <span className="font-mono text-[13px] font-bold" style={{ color: confidence.color }}>
          {confidence.label}
        </span>
      </div>

      {/* Reason tags */}
      {reasons.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {reasons.map((r) => (
            <span
              key={r}
              className="rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 font-mono text-[10px] text-white/52"
            >
              {r}
            </span>
          ))}
        </div>
      )}

      {/* Gate decision */}
      <div className="mt-5 flex items-center gap-2 border-t border-white/[0.06] pt-4">
        <TrendingUp className="h-3 w-3 text-white/26" aria-hidden />
        <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-white/26">
          vol_regime_v2
        </span>
        <div className="ml-auto">
          {isPromoted ? (
            <span className="rounded border border-[rgba(0,255,255,0.22)] bg-[rgba(0,255,255,0.06)] px-2 py-0.5 font-mono text-[10px] font-semibold text-[rgba(0,255,255,0.72)]">
              검증됨 ✓
            </span>
          ) : (
            <span className="rounded border border-white/8 bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-white/26">
              관찰중
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Main export ─────────────────────────────────────────────────────────── */

export function SovereignCommandPanel({
  sovereignIndex,
  riskOverlay,
}: {
  sovereignIndex: SovereignIndex | null;
  riskOverlay: RiskOverlay | null;
}) {
  if (!sovereignIndex && !riskOverlay) return null;

  const both = sovereignIndex != null && riskOverlay != null;

  return (
    <section className="border-b border-white/10 px-6 py-10 md:px-20">
      <div className="mx-auto w-full max-w-6xl">
        {/* Section label */}
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span
              className="h-1.5 w-1.5 rounded-full bg-[#00ffff]"
              style={{ boxShadow: "0 0 6px rgba(0,255,255,0.55)" }}
            />
            <span className="font-mono text-[10px] uppercase tracking-[0.26em] text-white/40">
              Sovereign · 주력 지표
            </span>
          </div>
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/18">
            실시간 복합 분석
          </span>
        </div>

        {/* Unified card */}
        <div
          className="relative overflow-hidden rounded-lg shadow-[0_32px_80px_rgba(0,0,0,0.52)]"
          style={{
            border: "1px solid rgba(0,255,255,0.12)",
            background:
              "linear-gradient(135deg, rgba(0,255,255,0.05), rgba(10,9,8,0.98) 40%, rgba(16,185,129,0.04))",
          }}
        >
          {/* Top accent */}
          <div
            className="absolute inset-x-0 top-0 h-px"
            style={{
              background:
                "linear-gradient(to right, transparent, rgba(0,255,255,0.38), rgba(16,185,129,0.18), transparent)",
            }}
          />

          <div className={`grid gap-px bg-white/[0.05] ${both ? "md:grid-cols-2" : ""}`}>
            {sovereignIndex && <IndexPanel si={sovereignIndex} />}
            {riskOverlay && <StatePanel overlay={riskOverlay} />}
          </div>
        </div>
      </div>
    </section>
  );
}
