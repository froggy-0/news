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
    <div className="border-b border-[rgba(169,146,125,0.10)] pt-[68px]">
      {/* Stale warning strip */}
      {staleWarning && (
        <div className="border-b border-[var(--accent-warning)]/30 bg-[var(--accent-warning)]/8 px-6 py-2.5 md:px-20">
          <p className="text-[0.72rem] tracking-[0.1em] text-[var(--accent-warning)]">
            STALE ARTIFACT - reference date {referenceDate} may not reflect latest pipeline run
          </p>
        </div>
      )}

      {/* Main header area */}
      <div className="mx-auto w-full px-6 pt-10 pb-6 md:px-20">
        {/* Eyebrow */}
        <div className="mb-4 flex items-center gap-3">
          <span className="text-[0.65rem] uppercase tracking-[0.15em] text-[var(--accent-primary)]">
            Sovereign Brief
          </span>
          <span className="h-px w-6 bg-[rgba(169,146,125,0.18)]" />
          <span className="text-[0.65rem] uppercase tracking-[0.15em] text-[var(--taupe)]/50">
            Research Console
          </span>
        </div>

        {/* Title row */}
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="flex-1">
            <h1 className="text-[2.6rem] font-bold leading-[1.12] text-[var(--smoke)] md:text-[3.6rem]">
              Signal Intelligence Lab
            </h1>
            <p className="mt-3 max-w-2xl text-[0.78rem] leading-6 text-[var(--taupe)]/62">
              Granger temporal precedence · PCA hybrid index · lag-only alpha validation · target diagnostics
              - all resolved against the same parquet reference date.
            </p>

            {!diagnosticsReady && (
              <div className="mt-5 max-w-xl rounded-2xl border border-[var(--accent-warning)]/24 bg-[var(--accent-warning)]/7 px-4 py-3.5">
                <p className="font-mono text-[0.65rem] uppercase tracking-[0.14em] text-[var(--accent-warning)]">
                  diagnostic artifact pending
                </p>
                <p className="mt-1.5 text-[0.76rem] leading-6 text-[var(--taupe)]/70">
                  Public JSON is legacy v1 - data quality, alpha, target, and rawStats blocks will populate after the next v2 sentiment-join run.
                </p>
              </div>
            )}
          </div>

          {/* Run metadata card */}
          <div className="shrink-0 rounded-md border border-[rgba(169,146,125,0.14)] bg-[rgba(242,244,243,0.03)] px-5 py-4">
            <p className="mb-3 text-[0.6rem] uppercase tracking-[0.14em] text-[var(--taupe)]/45">Run Metadata</p>
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
      <div className="mx-auto w-full px-6 pb-8 md:px-20">
        <div className="grid gap-2.5 sm:grid-cols-2 md:grid-cols-4" aria-label="Analysis KPI summary">
          <KpiCard
            slot="A"
            label="감성이 먼저"
            caption="news → market"
            signal={summary.strongestForward}
          />
          <KpiCard
            slot="B"
            label="시장이 먼저"
            caption="market → news"
            signal={summary.strongestReverse}
          />
          <KpiMetric
            label="의미 있는 관계"
            value={`${summary.significantCount}`}
            caption="adj p-value < 0.05"
            tone={summary.significantCount > 0 ? "cyan" : "muted"}
          />
          <KpiMetric
            label="종합 신호 핵심"
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
    <article className="group relative overflow-hidden rounded-md border border-[rgba(169,146,125,0.14)] bg-[rgba(242,244,243,0.03)] p-4 transition-colors duration-300 hover:border-[rgba(169,146,125,0.24)] hover:bg-[rgba(242,244,243,0.05)]">
      <div className="absolute inset-0 rounded-md opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: "linear-gradient(90deg, rgba(73,17,28,0.08), transparent 72%)" }}
      />
      <p className="text-[0.6rem] uppercase tracking-[0.14em] text-[var(--taupe)]/45">{label}</p>
      <p className="mt-0.5 text-[0.58rem] tracking-[0.08em] text-[var(--accent-primary)]/70">
        {caption}
      </p>
      <p className="mt-3.5 text-[0.9rem] font-semibold leading-5 text-[var(--smoke)]/86">
        {hasSignal ? signal.label : "No significant relationship"}
      </p>
      <p className="mt-1.5 text-[0.65rem] text-[var(--taupe)]/48">
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
          : "rgba(169,146,125,0.62)";

  return (
    <article className="group relative overflow-hidden rounded-md border border-[rgba(169,146,125,0.14)] bg-[rgba(242,244,243,0.03)] p-4 transition-colors duration-300 hover:border-[rgba(169,146,125,0.24)] hover:bg-[rgba(242,244,243,0.05)]">
      <div className="absolute inset-0 rounded-md opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: `linear-gradient(90deg, color-mix(in srgb, ${accentColor} 10%, transparent), transparent 72%)` }}
      />
      <p className="text-[0.6rem] uppercase tracking-[0.14em] text-[var(--taupe)]/45">{label}</p>
      <p
        className="mt-3.5 text-[1.05rem] font-semibold leading-5"
        style={{ color: accentColor }}
      >
        {value}
      </p>
      <p className="mt-1.5 text-[0.65rem] text-[var(--taupe)]/48">{caption}</p>
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
      : "text-[var(--smoke)]/76";
  return (
    <div>
      <dt className="text-[0.62rem] uppercase tracking-[0.12em] text-[var(--taupe)]/45">{label}</dt>
      <dd className={`mt-0.5 text-[0.7rem] tracking-[0.04em] ${valueClass}`}>{value}</dd>
    </div>
  );
}
