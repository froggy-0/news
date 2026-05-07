import React from "react";
import { BarChart2, TrendingUp } from "lucide-react";

import type { RiskOverlay, SovereignIndex } from "@schema/brief.types";

const ZONE_CONFIG = {
  bull: {
    color: "#10b981",
    borderColor: "rgba(16,185,129,0.28)",
    bgGradient: "linear-gradient(135deg,rgba(16,185,129,0.12),rgba(10,9,8,0.96) 42%,rgba(16,185,129,0.04))",
    topLine: "var(--accent-green)",
    label: "강세 구간",
  },
  neutral: {
    color: "#64748b",
    borderColor: "rgba(100,116,139,0.28)",
    bgGradient: "linear-gradient(135deg,rgba(100,116,139,0.08),rgba(10,9,8,0.96) 42%,rgba(100,116,139,0.04))",
    topLine: "rgba(100,116,139,0.6)",
    label: "중립 구간",
  },
  bear: {
    color: "#ef4444",
    borderColor: "rgba(246,70,93,0.32)",
    bgGradient: "linear-gradient(135deg,rgba(246,70,93,0.12),rgba(10,9,8,0.96) 42%,rgba(246,70,93,0.04))",
    topLine: "var(--accent-down)",
    label: "약세 구간",
  },
} as const;

function GaugeBar({ score, zone }: { score: number; zone: SovereignIndex["zone"] }) {
  const pct = Math.min(100, Math.max(0, score));
  const zoneColor = ZONE_CONFIG[zone].color;

  return (
    <div className="mt-5">
      {/* Scale labels */}
      <div className="mb-1.5 flex justify-between font-mono text-[9px] text-white/30">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>

      {/* Track */}
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-white/[0.08]">
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-[width]"
          style={{ width: `${pct}%`, background: zoneColor }}
        />
      </div>

      {/* Zone tick marks */}
      <div className="relative mt-1 flex">
        <div style={{ width: "30%" }} className="border-r border-white/16 pr-1 text-right font-mono text-[9px] text-white/24">
          30
        </div>
        <div style={{ width: "40%" }} className="border-r border-white/16 text-right font-mono text-[9px]" />
        <div style={{ width: "30%" }} className="pl-1 font-mono text-[9px] text-white/24">
          70
        </div>
      </div>
    </div>
  );
}

function ZoneLegend({ zone }: { zone: SovereignIndex["zone"] }) {
  const zones: Array<{ key: SovereignIndex["zone"]; color: string; label: string; range: string }> = [
    { key: "bull", color: "#10b981", label: "강세", range: "70 ↑" },
    { key: "neutral", color: "#64748b", label: "중립", range: "30 – 70" },
    { key: "bear", color: "#ef4444", label: "약세", range: "↓ 30" },
  ];

  return (
    <div className="mt-5 flex flex-col gap-2">
      {zones.map(({ key, color, label, range }) => {
        const isActive = key === zone;
        return (
          <div key={key} className="flex items-center gap-2.5">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: color, opacity: isActive ? 1 : 0.35 }}
            />
            <span
              className="font-mono text-[10px] uppercase tracking-[0.12em]"
              style={{ color: isActive ? color : "rgba(255,255,255,0.32)", fontWeight: isActive ? 700 : 400 }}
            >
              {range}
            </span>
            <span
              className="text-xs"
              style={{ color: isActive ? "rgba(255,255,255,0.88)" : "rgba(255,255,255,0.30)", fontWeight: isActive ? 600 : 400 }}
            >
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const REGIME_STATE_LABELS: Record<string, string> = {
  BullQuiet: "안정 상승",
  BullHeated: "과열 상승",
  BearPanic: "공포 하락",
  Choppy: "방향 불명",
  Transitional: "전환 구간",
};

const CONFIDENCE_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; border: string }
> = {
  HIGH: {
    label: "롱 활성",
    color: "#10b981",
    bg: "rgba(16,185,129,0.10)",
    border: "rgba(16,185,129,0.30)",
  },
  MEDIUM: {
    label: "신호 약",
    color: "#f0b90b",
    bg: "rgba(240,185,11,0.10)",
    border: "rgba(240,185,11,0.28)",
  },
  LOW: {
    label: "약세",
    color: "#ef4444",
    bg: "rgba(239,68,68,0.10)",
    border: "rgba(239,68,68,0.28)",
  },
  NONE: {
    label: "대기",
    color: "rgba(255,255,255,0.38)",
    bg: "rgba(255,255,255,0.05)",
    border: "rgba(255,255,255,0.12)",
  },
};

function RegimeSignalFooter({ overlay }: { overlay: RiskOverlay }) {
  const confidence = CONFIDENCE_CONFIG[overlay.signalConfidence ?? "NONE"] ?? CONFIDENCE_CONFIG.NONE;
  const regimeLabel = REGIME_STATE_LABELS[overlay.regimeState] ?? overlay.regimeState;
  const isPromoted = overlay.overlayGateDecision === "promote";

  return (
    <div className="border-t border-white/[0.06] bg-[#0b0a08]/90 px-5 py-3.5 md:px-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* Left: label */}
        <div className="flex items-center gap-1.5">
          <TrendingUp className="h-3 w-3 text-white/32" aria-hidden="true" />
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/32">
            레짐 신호 · vol_regime_v2
          </span>
        </div>

        {/* Right: pills */}
        <div className="ml-auto flex items-center gap-1.5">
          {/* Regime state */}
          <span className="rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-white/52">
            {regimeLabel}
          </span>

          {/* Signal confidence */}
          <span
            className="rounded border px-2 py-0.5 font-mono text-[10px] font-semibold"
            style={{
              color: confidence.color,
              background: confidence.bg,
              borderColor: confidence.border,
            }}
          >
            {confidence.label}
          </span>

          {/* Gate decision */}
          {isPromoted ? (
            <span className="rounded border border-[rgba(0,255,255,0.22)] bg-[rgba(0,255,255,0.06)] px-2 py-0.5 font-mono text-[10px] font-semibold text-[rgba(0,255,255,0.72)]">
              검증됨 ✓
            </span>
          ) : (
            <span className="rounded border border-white/8 bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-white/28">
              관찰중
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function SovereignIndexPanel({
  sovereignIndex,
  riskOverlay,
}: {
  sovereignIndex: SovereignIndex | null;
  riskOverlay?: RiskOverlay | null;
}) {
  if (!sovereignIndex) {
    return null;
  }

  const { score, labelKo, zone, qualityStatus } = sovereignIndex;
  const cfg = ZONE_CONFIG[zone];
  const isDegraded = qualityStatus !== "ok";

  return (
    <section className="border-b border-white/10 px-6 py-10 md:px-20">
      <div className="mx-auto w-full max-w-6xl">
        <div
          className="relative overflow-hidden rounded-lg shadow-[0_26px_70px_rgba(0,0,0,0.42)]"
          style={{ border: `1px solid ${cfg.borderColor}`, background: cfg.bgGradient }}
        >
          {/* Top accent line */}
          <div
            className="absolute inset-x-0 top-0 h-px"
            style={{ background: `linear-gradient(to right, transparent, ${cfg.topLine}, transparent)` }}
          />

          <div className="grid gap-px bg-white/[0.06] md:grid-cols-[1fr_1.2fr]">
            {/* Left: Score + icon */}
            <div className="bg-[#0b0a08]/95 p-5 md:p-6">
              <div className="flex items-center gap-3">
                <span
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border bg-white/[0.03]"
                  style={{ borderColor: cfg.borderColor, color: cfg.color }}
                >
                  <BarChart2 className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <p className="section-title" style={{ color: "#00ffff" }}>
                    Sovereign Index
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.22em] text-white/38">
                    BTC 시장 복합 지표
                  </p>
                </div>
              </div>

              <div className="mt-5 flex items-baseline gap-3">
                <span
                  className="font-mono text-[64px] font-bold leading-none tabular-nums"
                  style={{ color: cfg.color, letterSpacing: "-0.03em" }}
                >
                  {Math.round(score)}
                </span>
                <div className="flex flex-col gap-1">
                  <span className="font-mono text-sm text-white/38">/ 100</span>
                  <span className="text-sm font-bold" style={{ color: cfg.color }}>
                    {labelKo}
                  </span>
                </div>
              </div>

              {isDegraded && (
                <p className="mt-4 text-[11px] leading-relaxed text-white/36">
                  ⚠ 일부 데이터 누락으로 지수 신뢰도가 낮을 수 있어요
                </p>
              )}
            </div>

            {/* Right: Gauge + Zone legend */}
            <div className="bg-[#0b0a08]/95 p-5 md:p-6">
              <p className="section-title">현재 구간</p>
              <p
                className="mt-2 text-2xl font-black leading-none"
                style={{ color: cfg.color }}
              >
                {cfg.label}
              </p>

              <GaugeBar score={score} zone={zone} />
              <ZoneLegend zone={zone} />
            </div>
          </div>

          {/* Footer: Regime Signal (predictive track) */}
          {riskOverlay && <RegimeSignalFooter overlay={riskOverlay} />}
        </div>
      </div>
    </section>
  );
}
