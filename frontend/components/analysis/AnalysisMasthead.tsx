"use client";

import React from "react";

import type { GrangerCorrection } from "@schema/analysis.types";
import type { AnalysisSummary, DerivedSignal } from "@/lib/analysis-derive";
import { formatAdjustedPValue, formatQualityStatus } from "@/lib/analysis-derive";

export function AnalysisMasthead({
  referenceDate,
  generatedAtUtc,
  correction,
  staleWarning,
  summary,
  schemaVersion,
  diagnosticsReady,
}: {
  referenceDate: string;
  generatedAtUtc: string;
  correction: GrangerCorrection;
  staleWarning: boolean;
  summary: AnalysisSummary;
  schemaVersion?: string;
  diagnosticsReady: boolean;
}) {
  const generatedUtcShort = (() => {
    try {
      return new Date(generatedAtUtc).toISOString().replace("T", " ").slice(0, 16) + " UTC";
    } catch {
      return generatedAtUtc;
    }
  })();

  const artifactLabel = diagnosticsReady ? (schemaVersion ?? "v2") : "legacy v1";
  const artifactOk = diagnosticsReady;

  return (
    <div className="border-b border-white/10">
      {/* Stale warning strip */}
      {staleWarning && (
        <div className="border-b border-[var(--accent-warning)]/30 bg-[var(--accent-warning)]/8 px-6 py-2.5">
          <p className="font-mono text-[0.72rem] tracking-[0.1em] text-[var(--accent-warning)]">
            ⚠ STALE ARTIFACT — reference date {referenceDate} may not reflect latest pipeline run
          </p>
        </div>
      )}

      {/* Main header area */}
      <div className="mx-auto w-full max-w-6xl px-6 pt-10 pb-6">
        {/* Eyebrow */}
        <div className="mb-4 flex items-center gap-3">
          <span className="font-mono text-[0.65rem] uppercase tracking-[0.22em] text-[var(--accent-primary)]/60">
            Sovereign Brief
          </span>
          <span className="h-px w-6 bg-white/12" />
          <span className="font-mono text-[0.65rem] uppercase tracking-[0.22em] text-white/28">
            Research Console
          </span>
        </div>

        {/* Title row */}
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="flex-1">
            <h1
              className="text-[2.6rem] leading-[1.08] tracking-[-0.04em] text-white md:text-[3.6rem]"
              style={{ fontFamily: "var(--font-instrument-serif)", fontStyle: "italic" }}
            >
              Signal Intelligence Lab
            </h1>
            <p className="mt-3 max-w-2xl font-mono text-[0.78rem] leading-6 text-white/40">
              Granger causality · PCA hybrid index · lag-only alpha validation · target diagnostics
              — all resolved against the same parquet reference date.
            </p>

            {!diagnosticsReady && (
              <div className="mt-5 max-w-xl rounded-2xl border border-[var(--accent-warning)]/24 bg-[var(--accent-warning)]/7 px-4 py-3.5">
                <p className="font-mono text-[0.65rem] uppercase tracking-[0.14em] text-[var(--accent-warning)]">
                  diagnostic artifact pending
                </p>
                <p className="mt-1.5 text-[0.76rem] leading-6 text-white/52">
                  Public JSON is legacy v1 — data quality, alpha, target, and rawStats blocks will populate after the next v2 sentiment-join run.
                </p>
              </div>
            )}
          </div>

          {/* Run metadata card */}
          <div className="shrink-0 rounded-2xl border border-white/10 bg-white/[0.028] px-5 py-4 font-mono">
            <p className="mb-3 text-[0.6rem] uppercase tracking-[0.2em] text-white/28">Run Metadata</p>
            <dl className="grid grid-cols-2 gap-x-8 gap-y-2.5 text-[0.7rem]">
              <MetaItem label="Reference" value={referenceDate} />
              <MetaItem label="Generated" value={generatedUtcShort} />
              <MetaItem
                label="Artifact"
                value={artifactLabel}
                accent={artifactOk}
                warning={!artifactOk}
              />
              <MetaItem
                label="Diagnostics"
                value={diagnosticsReady ? "complete" : "pending"}
                accent={diagnosticsReady}
                warning={!diagnosticsReady}
              />
              <MetaItem label="Tests run" value={`${correction.nTests}`} />
              <MetaItem
                label="Correction"
                value={correction.method.toUpperCase().replace("_", "-")}
                accent
              />
            </dl>
          </div>
        </div>
      </div>

      {/* KPI strip — horizontal summary bar */}
      <div className="mx-auto w-full max-w-6xl px-6 pb-8">
        <div className="grid gap-2.5 sm:grid-cols-2 md:grid-cols-4" aria-label="Analysis KPI summary">
          <KpiCard
            slot="A"
            label="Sentiment Leads"
            caption="news → market"
            signal={summary.strongestForward}
          />
          <KpiCard
            slot="B"
            label="Market Leads"
            caption="market → news"
            signal={summary.strongestReverse}
          />
          <KpiMetric
            label="Significant"
            value={`${summary.significantCount}`}
            caption="adj p-value < 0.05"
            tone={summary.significantCount > 0 ? "cyan" : "muted"}
          />
          <KpiMetric
            label="Top PCA Driver"
            value={summary.topPcaDriver?.label ?? "—"}
            caption={
              summary.topPcaDriver
                ? `${summary.topPcaDriver.loading >= 0 ? "+" : ""}${summary.topPcaDriver.loading.toFixed(3)} · ${(summary.coverageRatio * 100).toFixed(1)}% coverage`
                : `quality: ${formatQualityStatus(summary.qualityStatus)}`
            }
            tone={
              summary.topPcaDriver?.direction === "negative"
                ? "red"
                : summary.topPcaDriver
                  ? "green"
                  : "muted"
            }
          />
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  caption,
  signal,
}: {
  slot: string;
  label: string;
  caption: string;
  signal: DerivedSignal | null;
}) {
  const hasSignal = signal !== null;
  return (
    <article className="group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.028] p-4 transition-all duration-300 hover:border-white/18 hover:bg-white/[0.04]">
      <div className="absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(0,255,255,0.04), transparent 70%)" }}
      />
      <p className="font-mono text-[0.6rem] uppercase tracking-[0.18em] text-white/28">{label}</p>
      <p className="mt-0.5 font-mono text-[0.58rem] tracking-[0.08em] text-[var(--accent-primary)]/50">
        {caption}
      </p>
      <p className="mt-3.5 text-[0.9rem] font-semibold leading-5 text-white/86">
        {hasSignal ? signal.label : "No significant relationship"}
      </p>
      <p className="mt-1.5 font-mono text-[0.65rem] text-white/34">
        {hasSignal && signal.lag !== null
          ? `lag ${signal.lag}d · ${formatAdjustedPValue(signal.adjustedPValue)}${signal.significant ? " · significant" : ""}`
          : "no test results"}
      </p>
    </article>
  );
}

function KpiMetric({
  label,
  value,
  caption,
  tone,
}: {
  label: string;
  value: string;
  caption: string;
  tone: "cyan" | "green" | "red" | "muted";
}) {
  const accentColor =
    tone === "green"
      ? "var(--accent-green)"
      : tone === "red"
        ? "var(--accent-down)"
        : tone === "cyan"
          ? "var(--accent-primary)"
          : "rgba(255,255,255,0.38)";

  return (
    <article className="group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.028] p-4 transition-all duration-300 hover:border-white/18 hover:bg-white/[0.04]">
      <div className="absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: `radial-gradient(ellipse at 50% 0%, color-mix(in srgb, ${accentColor} 8%, transparent), transparent 70%)` }}
      />
      <p className="font-mono text-[0.6rem] uppercase tracking-[0.18em] text-white/28">{label}</p>
      <p
        className="mt-3.5 text-[1.05rem] font-semibold leading-5"
        style={{ color: accentColor }}
      >
        {value}
      </p>
      <p className="mt-1.5 font-mono text-[0.65rem] text-white/34">{caption}</p>
    </article>
  );
}

function MetaItem({
  label,
  value,
  accent,
  warning,
}: {
  label: string;
  value: string;
  accent?: boolean;
  warning?: boolean;
}) {
  const valueClass = warning
    ? "text-[var(--accent-warning)]"
    : accent
      ? "text-[var(--accent-primary)]"
      : "text-white/76";
  return (
    <div>
      <dt className="text-[0.62rem] uppercase tracking-[0.12em] text-white/28">{label}</dt>
      <dd className={`mt-0.5 text-[0.7rem] tracking-[0.04em] ${valueClass}`}>{value}</dd>
    </div>
  );
}
