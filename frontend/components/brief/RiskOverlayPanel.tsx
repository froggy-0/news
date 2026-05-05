import React from "react";
import { Activity, Gauge, ShieldCheck } from "lucide-react";

import type { RiskOverlay } from "@schema/brief.types";

type Tone = "positive" | "warning" | "negative" | "neutral";

const REGIME_LABELS: Record<string, { label: string; tone: Tone }> = {
  BullQuiet: { label: "안정 상승", tone: "positive" },
  BullHeated: { label: "과열 상승", tone: "warning" },
  BearPanic: { label: "공포 하락", tone: "negative" },
  Choppy: { label: "방향 불명", tone: "warning" },
  Transitional: { label: "전환 구간", tone: "neutral" },
};

const VOL_LABELS: Record<string, string> = {
  Low: "낮음",
  Mid: "보통",
  High: "높음",
};

const VOL_TREND_LABELS: Record<string, string> = {
  rising: "상승 중",
  falling: "하락 중",
  stable: "안정",
};

const CONFIDENCE_LABELS: Record<string, { label: string; tone: Tone }> = {
  HIGH: { label: "강함", tone: "positive" },
  MEDIUM: { label: "보통", tone: "warning" },
  LOW: { label: "낮음", tone: "neutral" },
  NONE: { label: "대기", tone: "neutral" },
};

function toneClasses(tone: Tone): string {
  if (tone === "positive") return "border-[rgba(14,203,129,0.28)] text-[var(--accent-green)]";
  if (tone === "negative") return "border-[rgba(246,70,93,0.32)] text-[var(--accent-down)]";
  if (tone === "warning") return "border-[rgba(240,185,11,0.34)] text-[var(--accent-warning)]";
  return "border-white/12 text-white/76";
}

function statusCopy(overlay: RiskOverlay): string {
  const regime = REGIME_LABELS[overlay.regimeState]?.label ?? overlay.regimeState;
  const vol = VOL_LABELS[overlay.volLevel] ?? overlay.volLevel;
  return `${regime} · 변동성 ${vol}`;
}

export function RiskOverlayPanel({ overlay }: { overlay: RiskOverlay | null }) {
  if (!overlay) {
    return null;
  }

  const regime = REGIME_LABELS[overlay.regimeState] ?? {
    label: overlay.regimeState,
    tone: "neutral" as Tone,
  };
  const confidence = CONFIDENCE_LABELS[overlay.signalConfidence ?? "NONE"] ?? CONFIDENCE_LABELS.NONE;
  const volLabel = VOL_LABELS[overlay.volLevel] ?? overlay.volLevel;
  const volTrend = VOL_TREND_LABELS[overlay.volTrend] ?? overlay.volTrend;
  const reasons = overlay.signalReasonLabels.slice(0, 3);

  return (
    <section className="border-b border-white/10 px-6 py-10 md:px-20">
      <div className="mx-auto w-full max-w-6xl">
        <div className="relative overflow-hidden rounded-lg border border-[rgba(240,185,11,0.24)] bg-[linear-gradient(135deg,rgba(240,185,11,0.12),rgba(10,9,8,0.96)_42%,rgba(14,203,129,0.06))] shadow-[0_26px_70px_rgba(0,0,0,0.42)]">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--accent-warning)] to-transparent" />
          <div className="grid gap-px bg-white/[0.06] md:grid-cols-[1.05fr_0.9fr_1.05fr]">
            <div className="bg-[#0b0a08]/95 p-5 md:p-6">
              <div className="flex items-center gap-3">
                <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md border bg-white/[0.03] ${toneClasses(regime.tone)}`}>
                  <Activity className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="section-title text-[var(--accent-warning)]">시장 상태</p>
                  <p className="mt-2 text-2xl font-black leading-none text-white md:text-[28px]">{regime.label}</p>
                </div>
              </div>
              <p className="mt-4 text-sm leading-7 text-white/58">
                {overlay.regimeDescription || statusCopy(overlay)}
              </p>
            </div>

            <div className="bg-[#0b0a08]/95 p-5 md:p-6">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-white/12 bg-white/[0.03] text-white/72">
                  <Gauge className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <p className="section-title">변동성</p>
                  <p className="mt-2 text-xl font-black leading-none text-white">{volLabel}</p>
                </div>
              </div>
              <div className="mt-5 flex items-center justify-between gap-3 rounded-md border border-white/8 bg-white/[0.025] px-3 py-2">
                <span className="text-[11px] font-mono uppercase tracking-[0.14em] text-white/38">Flow</span>
                <span className="text-sm font-bold text-white/78">{volTrend}</span>
              </div>
            </div>

            <div className="bg-[#0b0a08]/95 p-5 md:p-6">
              <div className="flex items-center gap-3">
                <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md border bg-white/[0.03] ${toneClasses(confidence.tone)}`}>
                  <ShieldCheck className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <p className="section-title">오늘의 신호</p>
                  <p className="mt-2 text-xl font-black leading-none text-white">{confidence.label}</p>
                </div>
              </div>
              {reasons.length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {reasons.map((reason) => (
                    <span
                      key={reason}
                      className="rounded-md border border-[rgba(240,185,11,0.22)] bg-[rgba(240,185,11,0.08)] px-2.5 py-1 text-xs font-semibold leading-5 text-[rgba(248,250,252,0.78)]"
                    >
                      {reason}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm leading-7 text-white/54">이번 집계에서는 신호 근거를 추가로 확인하지 못했어요.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
