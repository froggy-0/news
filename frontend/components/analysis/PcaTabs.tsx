"use client";

import React from "react";
import { useMemo, useState } from "react";

import type { PcaIndex, PcaSection } from "@schema/analysis.types";
import {
  formatFeatureLabel,
  formatQualityReason,
  formatQualityStatus,
  topPcaDriver,
} from "@/lib/analysis-derive";

type TabId = "full" | "core";

const TAB_LABELS: Record<TabId, string> = {
  full: "Extended",
  core: "Core",
};

export function PcaTabs({ pca }: { pca: PcaSection }) {
  const [active, setActive] = useState<TabId>("full");
  const data = pca[active];
  const driver = topPcaDriver(data);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            지표 기여도
          </p>
          <p className="mt-2 max-w-2xl text-[0.82rem] leading-6 text-white/46">
            종합 신호를 올리거나 낮추는 지표의 방향과 설명력 비중을 함께 봅니다.
          </p>
        </div>
        <div className="inline-flex w-fit overflow-hidden rounded-full border border-[rgba(169,146,125,0.1)] bg-black/24 p-1">
          {(["full", "core"] as TabId[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActive(tab)}
              className={`rounded-full px-4 py-2 font-mono text-[0.68rem] uppercase tracking-[0.14em] transition ${
                active === tab
                  ? "bg-white/12 text-white shadow-[0_0_22px_rgba(73,17,28,0.18)]"
                  : "text-white/34 hover:text-white/66"
              }`}
              aria-pressed={active === tab}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>
      </div>

      {data.status !== "ok" ? (
        <EmptyState status={data.status} />
      ) : (
        <>
          <div className="grid gap-2 md:grid-cols-5">
            <MetricChip label="Components" value={`${data.nComponents}`} />
            <MetricChip label="설명력" value={`${(data.explainedVariance * 100).toFixed(1)}%`} />
            <MetricChip label="Coverage" value={`${(data.coverageRatio * 100).toFixed(1)}%`} />
            <MetricChip label="Features used" value={`${data.selectedFeatures.length}`} />
            <MetricChip label="Excluded" value={`${data.excludedFeatures.length}`} />
          </div>

          <QualityNotice data={data} />

          {driver && (
            <div className="rounded-2xl border border-[rgba(169,146,125,0.1)] bg-black/22 p-4">
              <p className="font-mono text-[0.64rem] uppercase tracking-[0.16em] text-white/34">
                가장 큰 기여 지표
              </p>
              <p className="mt-2 text-[1rem] font-semibold text-white/86">{driver.label}</p>
              <p className="mt-1 font-mono text-[0.68rem] text-white/40">
                {driver.loading >= 0 ? "+" : ""}
                {driver.loading.toFixed(3)} · {driver.direction === "positive" ? "raises composite signal" : "lowers composite signal"}
              </p>
            </div>
          )}

          <PcaIndexView data={data} />
        </>
      )}
    </div>
  );
}

function PcaIndexView({ data }: { data: PcaIndex }) {
  const [activeFeature, setActiveFeature] = useState<string | null>(null);
  const entries = useMemo(
    () => Object.entries(data.loadings).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])),
    [data.loadings],
  );
  const maxAbs = Math.max(...entries.map(([, value]) => Math.abs(value)), 0.001);
  const totalAbs = entries.reduce((sum, [, value]) => sum + Math.abs(value), 0);

  return (
    <div className="space-y-4">
      <div className="hidden grid-cols-[minmax(120px,0.9fr)_minmax(220px,2fr)_84px] gap-4 px-3 font-mono text-[0.62rem] uppercase tracking-[0.14em] text-white/28 md:grid">
        <span>Feature</span>
        <span className="text-center">Lowers / Raises</span>
        <span className="text-right">Weight</span>
      </div>
      <div className="space-y-2.5">
        {entries.map(([feature, loading], index) => {
          const abs = Math.abs(loading);
          const share = totalAbs > 0 ? (abs / totalAbs) * 100 : 0;
          const pct = (abs / maxAbs) * 50;
          const positive = loading >= 0;
          const active = activeFeature === feature;
          return (
            <article
              key={feature}
              className={`grid gap-3 rounded-2xl border p-3 transition md:grid-cols-[minmax(120px,0.9fr)_minmax(220px,2fr)_84px] md:items-center ${
                active
                  ? "border-white/22 bg-white/[0.06]"
                  : "border-[rgba(169,146,125,0.08)] bg-white/[0.02] hover:border-[rgba(169,146,125,0.16)] hover:bg-white/[0.04]"
              }`}
              onMouseEnter={() => setActiveFeature(feature)}
              onMouseLeave={() => setActiveFeature(null)}
              onFocus={() => setActiveFeature(feature)}
              onBlur={() => setActiveFeature(null)}
              tabIndex={0}
              style={{ animation: `compassRow 420ms ease-out ${index * 45}ms both` }}
            >
              <style>{`
                @keyframes compassRow {
                  from { opacity: 0; transform: translateY(8px); }
                  to { opacity: 1; transform: translateY(0); }
                }
              `}</style>
              <div>
                <p className="text-[0.88rem] font-semibold leading-5 text-white/82">
                  {formatFeatureLabel(feature)}
                </p>
                <p className="mt-1 font-mono text-[0.63rem] text-white/32">rank #{index + 1}</p>
              </div>

              <div className="relative min-h-[42px]">
                <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-white/16" />
                <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-white/8" />
                <div
                  className="absolute top-1/2 h-3 -translate-y-1/2 rounded-full transition-all duration-300"
                  style={{
                    width: `${Math.max(8, pct)}%`,
                    ...(positive
                      ? { left: "50%", background: "rgba(109,189,122,0.72)" }
                      : { right: "50%", background: "rgba(224,82,82,0.62)" }),
                    boxShadow: active
                      ? positive
                        ? "0 0 24px rgba(109,189,122,0.22)"
                        : "0 0 24px rgba(224,82,82,0.22)"
                      : "none",
                  }}
                />
                <div className="absolute inset-x-0 bottom-0 flex justify-between font-mono text-[0.58rem] uppercase tracking-[0.1em] text-white/22">
                  <span>lowers</span>
                  <span>raises</span>
                </div>
              </div>

              <div className="md:text-right">
                <p className="font-mono text-[0.75rem] tabular-nums text-white/78">
                  {loading >= 0 ? "+" : ""}
                  {loading.toFixed(3)}
                </p>
                <p className="mt-1 font-mono text-[0.64rem] text-white/34">{share.toFixed(1)}%</p>
                <p
                  className={`mt-1 text-[0.68rem] leading-5 ${
                    positive ? "text-[var(--accent-green)]/72" : "text-[var(--accent-down)]/72"
                  }`}
                >
                  {positive ? "raises" : "lowers"}
                </p>
              </div>
            </article>
          );
        })}
      </div>

      {data.excludedFeatures.length > 0 && (
        <div className="rounded-2xl border border-[rgba(169,146,125,0.08)] bg-black/20 p-4">
          <p className="font-mono text-[0.64rem] uppercase tracking-[0.16em] text-white/30">
            함께 쓰기 어려워 제외한 지표
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {data.excludedFeatures.map((feature, index) => (
              <span
                key={`${feature.feature}-${index}`}
                className="rounded-full border border-[var(--accent-down)]/18 bg-[var(--accent-down)]/8 px-3 py-1 font-mono text-[0.65rem] text-[var(--accent-down)]/74"
              >
                {formatFeatureLabel(feature.feature)}
                {feature.reason ? ` · ${formatQualityReason(feature.reason)}` : ""}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function QualityNotice({ data }: { data: PcaIndex }) {
  const [open, setOpen] = useState(false);
  const degraded = data.qualityStatus === "degraded" || data.qualityStatus === "critical";
  if (!degraded) {
    return (
      <div className="rounded-2xl border border-[var(--accent-green)]/16 bg-[var(--accent-green)]/5 px-4 py-3">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-[var(--accent-green)]/80">
          데이터 상태 참고 필요 · composite signal computed from available features
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-[var(--accent-warning)]/22 bg-[var(--accent-warning)]/7 p-4">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 text-left"
        aria-expanded={open}
      >
        <span className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-[var(--accent-warning)]">
          데이터 상태 참고 필요 · Data quality {formatQualityStatus(data.qualityStatus)} · coverage {(data.coverageRatio * 100).toFixed(1)}%
        </span>
        <span className="font-mono text-[0.68rem] text-white/36">{open ? "collapse" : "view reasons"}</span>
      </button>
      {open && (
        <ul className="mt-3 space-y-1 border-t border-white/8 pt-3">
          {(data.qualityReasons.length > 0 ? data.qualityReasons : ["Data quality is low — interpret with caution."]).map(
            (reason, index) => (
              <li key={`${reason}-${index}`} className="font-mono text-[0.7rem] text-white/46">
                {formatQualityReason(reason)}
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function MetricChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[rgba(169,146,125,0.1)] bg-black/24 px-3 py-3">
      <p className="font-mono text-[0.58rem] uppercase tracking-[0.14em] text-white/28">{label}</p>
      <p className="mt-1 font-mono text-[0.78rem] tabular-nums text-white/76">{value}</p>
    </div>
  );
}

function EmptyState({ status }: { status: string }) {
  return (
    <div className="flex min-h-[260px] flex-col items-center justify-center gap-3 rounded-2xl border border-[rgba(169,146,125,0.08)] bg-black/20">
      <p className="font-mono text-[0.72rem] uppercase tracking-[0.16em] text-[var(--text-muted)]">
        Composite signal not computed
      </p>
      <p className="font-mono text-[0.66rem] text-white/34">Data status: {formatQualityStatus(status)}</p>
    </div>
  );
}
