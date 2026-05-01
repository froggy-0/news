"use client";

import React, { useMemo, useState } from "react";
import {
  Activity,
  Database,
  LineChart,
  ShieldCheck,
  TableProperties,
  Target,
} from "lucide-react";

import type {
  AlphaSection,
  ArtifactSummary,
  DataQualitySection,
  JsonObject,
  JsonValue,
  SentimentInsightArtifact,
  TargetsSection,
} from "@schema/analysis.types";
import { formatFeatureLabel } from "@/lib/analysis-derive";

type Tone = "cyan" | "green" | "yellow" | "red" | "muted";

function isJsonObject(value: JsonValue | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function objectEntries(value: JsonObject | undefined): [string, JsonValue][] {
  return Object.entries(value ?? {});
}

function objectArray(value: JsonValue[] | undefined): JsonObject[] {
  return (value ?? []).filter(isJsonObject);
}

function numberField(record: JsonObject | undefined, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function firstNumberField(record: JsonObject | undefined, keys: string[]): number | null {
  for (const key of keys) {
    const value = numberField(record, key);
    if (value !== null) return value;
  }
  return null;
}

function stringField(record: JsonObject | undefined, key: string): string {
  const value = record?.[key];
  return typeof value === "string" ? value : "";
}

function formatPercent(value: number | null | undefined, digits = 1): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

function formatNumber(value: number | null | undefined, digits = 0): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatValue(value: JsonValue | undefined): string {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "number") {
    if (Math.abs(value) <= 1) return value.toFixed(3);
    return formatNumber(value, 2);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return `${value.length} items`;
  return objectEntries(value).slice(0, 2).map(([key, item]) => `${key}:${formatValue(item)}`).join(" · ");
}

function toneClass(tone: Tone): string {
  if (tone === "green") return "border-[var(--accent-green)]/30 bg-[var(--accent-green)]/8 text-[var(--accent-green)]";
  if (tone === "yellow") return "border-[var(--accent-warning)]/30 bg-[var(--accent-warning)]/8 text-[var(--accent-warning)]";
  if (tone === "red") return "border-[var(--accent-down)]/30 bg-[var(--accent-down)]/8 text-[var(--accent-down)]";
  if (tone === "cyan") return "border-[var(--accent-green)]/26 bg-[var(--accent-green)]/6 text-[var(--accent-green)]";
  return "border-white/10 bg-white/[0.03] text-white/46";
}

function bestBaselineHitRate(baselines: JsonObject | undefined): number | null {
  let best: number | null = null;
  for (const [, raw] of objectEntries(baselines)) {
    if (!isJsonObject(raw)) continue;
    const hitRate = numberField(raw, "hit_rate");
    if (hitRate === null) continue;
    best = best === null ? hitRate : Math.max(best, hitRate);
  }
  return best;
}

function statusToneFromRatio(value: number | null | undefined, warning = 0.1): Tone {
  if (typeof value !== "number") return "muted";
  if (value <= warning / 2) return "green";
  if (value <= warning) return "yellow";
  return "red";
}

export function isFullDiagnosticArtifact(artifact: SentimentInsightArtifact): boolean {
  return artifact.schemaVersion === "sentiment-insight-v2" && objectEntries(artifact.rawStats).length > 0;
}

export function AnalysisOverviewDeck({ artifact }: { artifact: SentimentInsightArtifact }) {
  const summary = artifact.summary;
  const rows = artifact.dataQuality?.rows;
  const diagnosticsReady = isFullDiagnosticArtifact(artifact);
  const significantCount =
    summary && summary.grangerTestCount > 0
      ? summary.significantGrangerCount
      : artifact.granger.results.filter((row) => row.significant).length;
  const skipCount = artifact.granger.skips?.length ?? 0;
  const rawKeyCount = objectEntries(artifact.rawStats).length;
  const outlierTone = statusToneFromRatio(rows?.outlierFilteredRatio, 0.1);

  return (
    <section className="space-y-4" aria-label="Analysis report key status">
      {!diagnosticsReady && (
        <LegacyArtifactNotice
          title="Public artifact is still legacy v1"
          detail="The live latest.json only contains Granger / PCA. ffill breakdown, alpha, target diagnostics, and rawStats exist in the parquet but are not yet reflected in the public JSON. A v2 sentiment-join re-run is required."
        />
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
      <OverviewCard
        icon={<ShieldCheck className="h-4 w-4" />}
        label="Run State"
        value={diagnosticsReady ? (artifact.schemaVersion ?? "v2") : "legacy v1"}
        caption={`${artifact.runId} · ${artifact.referenceDate}`}
        tone={diagnosticsReady ? "cyan" : "yellow"}
      />
      <OverviewCard
        icon={<Database className="h-4 w-4" />}
        label="Rows"
        value={diagnosticsReady ? formatNumber(rows?.afterOutlierFilter ?? summary?.rowsAfterOutlierFilter) : "metadata pending"}
        caption={
          diagnosticsReady
            ? `raw ${formatNumber(rows?.beforeOutlierFilter ?? summary?.rowsBeforeOutlierFilter)} · masked ${formatPercent(rows?.outlierFilteredRatio, 1)}`
            : "exists in parquet · v2 JSON re-run required"
        }
        tone={diagnosticsReady ? outlierTone : "yellow"}
      />
      <OverviewCard
        icon={<Activity className="h-4 w-4" />}
        label="Granger"
        value={`${significantCount} significant`}
        caption={`${artifact.granger.correction.nTests} tests · ${skipCount} skips`}
        tone={skipCount > 0 ? "yellow" : "green"}
      />
      <OverviewCard
        icon={<LineChart className="h-4 w-4" />}
        label="Alpha"
        value={
          diagnosticsReady
            ? `${summary?.alphaCandidateCount ?? artifact.alpha?.hitRates.length ?? 0} signals`
            : "metadata pending"
        }
        caption={
          diagnosticsReady
            ? `${summary?.horizonMetricCount ?? objectEntries(artifact.alpha?.horizonMetrics).length} horizons · baseline linked`
            : "baseline/horizon metrics pending"
        }
        tone={diagnosticsReady ? "cyan" : "yellow"}
      />
      <OverviewCard
        icon={<Target className="h-4 w-4" />}
        label="Targets"
        value={
          diagnosticsReady
            ? `${summary?.targetCount ?? objectEntries(artifact.targets?.diagnostics).length}`
            : "metadata pending"
        }
        caption="fixed + volatility adjusted labels"
        tone={diagnosticsReady ? "green" : "yellow"}
      />
      <OverviewCard
        icon={<TableProperties className="h-4 w-4" />}
        label="Raw Metadata"
        value={diagnosticsReady ? `${rawKeyCount} keys` : "metadata pending"}
        caption={diagnosticsReady ? "parquet sentiment_join_stats" : "rawStats pending in latest.json"}
        tone={diagnosticsReady ? "green" : "yellow"}
      />
      </div>
    </section>
  );
}

function OverviewCard({
  icon,
  label,
  value,
  caption,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  caption: string;
  tone: Tone;
}) {
  return (
    <article className="analysis-depth-panel min-h-[148px] p-4">
      <div className={`inline-flex h-8 w-8 items-center justify-center rounded-full border ${toneClass(tone)}`}>
        {icon}
      </div>
      <p className="mt-4 font-mono text-[0.58rem] uppercase tracking-[0.16em] text-white/34">{label}</p>
      <p className="mt-2 text-[1rem] font-semibold leading-5 text-white/88">{value}</p>
      <p className="mt-2 font-mono text-[0.66rem] leading-5 text-white/40">{caption}</p>
    </article>
  );
}

export function DataQualityMatrix({
  dataQuality,
  diagnosticsReady,
}: {
  dataQuality?: DataQualitySection;
  diagnosticsReady: boolean;
}) {
  const sourceEntries = objectEntries(dataQuality?.structuredSources);
  const ffillEntries = objectEntries(dataQuality?.ffillBreakdown);
  const exclusionEntries = objectEntries(dataQuality?.exclusionCounts);
  const rows = dataQuality?.rows;

  return (
    <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
      <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
        {!diagnosticsReady && (
          <LegacyArtifactNotice
            title="Data quality metadata is not in latest.json yet"
            detail="The parquet contains row count, ffill breakdown, and structured source lineage — but the current public artifact is v1, so this block is empty until the next v2 run."
          />
        )}
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
              데이터 품질 매트릭스
            </p>
            <p className="mt-2 max-w-2xl font-mono text-[0.76rem] leading-6 text-white/42">
              Input data state to inspect before reading any signal output. Source lineage, ffill counts, and outlier masking in a single view.
            </p>
          </div>
          <div className="hidden rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/36 md:block">
            coverage first
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <MetricTile
            label="Rows used"
            value={diagnosticsReady ? formatNumber(rows?.afterOutlierFilter) : "pending"}
            detail={diagnosticsReady ? `raw ${formatNumber(rows?.beforeOutlierFilter)}` : "v2 artifact required"}
          />
          <MetricTile
            label="Masked"
            value={diagnosticsReady ? formatNumber(rows?.outlierFilteredCount) : "pending"}
            detail={diagnosticsReady ? formatPercent(rows?.outlierFilteredRatio, 2) : "parquet metadata pending"}
          />
          <MetricTile label="Exclusions" value={`${exclusionEntries.length}`} detail="feature exclusion groups" />
        </div>

        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {sourceEntries.length > 0 ? (
            sourceEntries.map(([source, payload]) => (
              <article key={source} className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                <p className="font-mono text-[0.62rem] uppercase tracking-[0.16em] text-white/30">{source}</p>
                <p className="mt-2 text-[0.9rem] font-semibold text-white/84">
                  {isJsonObject(payload) ? formatValue(payload.mode ?? payload.source ?? payload.status) : formatValue(payload)}
                </p>
                <p className="mt-2 line-clamp-2 font-mono text-[0.64rem] leading-5 text-white/36">
                  {formatValue(payload)}
                </p>
              </article>
            ))
          ) : (
            <EmptyPanel label="no source metadata" />
          )}
        </div>
      </div>

      <div className="space-y-4">
        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Forward Fill</p>
          <div className="mt-4 space-y-3">
            {ffillEntries.length > 0 ? (
              ffillEntries.map(([source, value]) => (
                <RatioRow key={source} label={source} value={formatValue(value)} ratio={typeof value === "number" ? Math.min(value / 365, 1) : null} />
              ))
            ) : (
              <EmptyPanel label="no ffill breakdown" />
            )}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Exclusions</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {exclusionEntries.length > 0 ? (
              exclusionEntries.map(([name, value]) => (
                <span key={name} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.64rem] text-white/52">
                  {name}: {formatValue(value)}
                </span>
              ))
            ) : (
              <span className="font-mono text-[0.68rem] text-white/32">no exclusions</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function AlphaValidationBoard({
  alpha,
  summary,
  diagnosticsReady,
  meta,
}: {
  alpha?: AlphaSection;
  summary?: ArtifactSummary;
  diagnosticsReady: boolean;
  meta?: JsonObject;
}) {
  const horizons = useMemo(
    () => objectEntries(alpha?.horizonMetrics).map(([key]) => key).sort((a, b) => Number(a) - Number(b)),
    [alpha?.horizonMetrics],
  );
  const [activeHorizon, setActiveHorizon] = useState(horizons[0] ?? "1");
  const horizonRaw = alpha?.horizonMetrics?.[activeHorizon];
  const horizon = isJsonObject(horizonRaw) ? horizonRaw : undefined;
  const allHitRates = objectArray(isJsonObject(horizon) && Array.isArray(horizon.hit_rates) ? horizon.hit_rates : alpha?.hitRates);
  const horizonBacktest = objectArray(isJsonObject(horizon) && Array.isArray(horizon.backtest) ? horizon.backtest : alpha?.backtest);
  const baselineRaw = alpha?.baselineMetrics?.[activeHorizon];
  const baselines = isJsonObject(baselineRaw) ? baselineRaw : undefined;
  const bestBaseline = bestBaselineHitRate(baselines);

  const regularRows = allHitRates.filter((r) => !r.research_rule);
  const researchRows = allHitRates.filter((r) => r.research_rule === true);
  const promotedRows = regularRows.filter((r) => r.promoted_from_research_rule === true);
  const topSignals = [...regularRows]
    .sort((a, b) => (numberField(b, "hit_rate") ?? -1) - (numberField(a, "hit_rate") ?? -1))
    .slice(0, 5);

  // Gate stats: prefer horizon-level gateStats if present, fall back to alpha.gateStats
  const horizonGateStats = isJsonObject(horizon?.gateStats) ? (horizon.gateStats as JsonObject) : undefined;
  const gateStats = horizonGateStats ?? (isJsonObject(alpha?.gateStats) ? alpha?.gateStats : undefined);
  const decisionPromote = typeof gateStats?.decisionPromoteCount === "number" ? gateStats.decisionPromoteCount : null;
  const strictPromote = typeof gateStats?.decisionStrictPromoteCount === "number" ? gateStats.decisionStrictPromoteCount : null;
  const gapRatio = typeof gateStats?.gapRatio === "number" ? gateStats.gapRatio : null;
  const overlayPromotionGate = isJsonObject(alpha?.promotionGate?.volRegimeV2Overlay)
    ? alpha?.promotionGate?.volRegimeV2Overlay
    : undefined;

  const sharpeChangeDate = typeof meta?.sharpeBasisChangeDate === "string" ? meta.sharpeBasisChangeDate : null;
  const annualizationNote = typeof meta?.annualizationNote === "string" ? meta.annualizationNote : null;

  return (
    <div className="space-y-5">
      {!diagnosticsReady && (
        <LegacyArtifactNotice
          title="Alpha metrics are waiting for v2 artifact"
          detail="The parquet contains baseline_metrics, horizon_metrics, and walk_forward_horizons, but the current latest.json is legacy v1 — alpha panel left empty until re-run."
        />
      )}
      {sharpeChangeDate && annualizationNote && (
        <div className="rounded-xl border border-[var(--accent-warning)]/30 bg-[var(--accent-warning)]/8 px-4 py-3" role="note" aria-label="Sharpe annualization change notice">
          <p className="font-mono text-[0.66rem] uppercase tracking-[0.14em] text-[var(--accent-warning)]">
            Sharpe basis changed · {sharpeChangeDate}
          </p>
          <p className="mt-1 font-mono text-[0.70rem] leading-5 text-white/60">
            {annualizationNote}
          </p>
        </div>
      )}
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            Alpha validation
          </p>
          <p className="mt-2 max-w-2xl font-mono text-[0.76rem] leading-6 text-white/40">
            Candidate signals must show baseline uplift to be promoted. Performance is evaluated on lag-only 1d / 3d / 7d forward returns, not contemporaneous correlation.
          </p>
        </div>
        <div className="inline-flex w-fit overflow-hidden rounded-full border border-white/10 bg-black/24 p-1">
          {(horizons.length > 0 ? horizons : ["1"]).map((horizonKey) => (
            <button
              key={horizonKey}
              type="button"
              onClick={() => setActiveHorizon(horizonKey)}
              className={`cursor-pointer rounded-full px-4 py-2 font-mono text-[0.68rem] uppercase tracking-[0.14em] transition ${
                activeHorizon === horizonKey
                  ? "bg-white/12 text-white shadow-[0_0_22px_rgba(73,17,28,0.18)]"
                  : "text-white/34 hover:text-white/66"
              }`}
              aria-pressed={activeHorizon === horizonKey}
            >
              {horizonKey}d
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile
          label="Candidate signals"
          value={diagnosticsReady ? `${summary?.alphaCandidateCount ?? alpha?.hitRates.length ?? 0}` : "pending"}
          detail="lag-only predictors"
        />
        <MetricTile
          label="Horizon"
          value={diagnosticsReady ? `${activeHorizon}d` : "pending"}
          detail={diagnosticsReady ? stringField(horizon, "return_col") || "return target" : "v2 artifact required"}
        />
        <MetricTile
          label="Best baseline"
          value={diagnosticsReady ? formatPercent(bestBaseline, 1) : "pending"}
          detail="best reference model"
        />
        <MetricTile
          label="Walk-forward"
          value={diagnosticsReady ? `${objectEntries(alpha?.walkForwardHorizons).length}` : "pending"}
          detail="full/core folds"
        />
      </div>

      {/* Gate stats: decision vs decision_strict gap */}
      {gateStats && decisionPromote !== null && strictPromote !== null && (
        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Gate · decision vs strict</p>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-3">
              <span className={`rounded-full border px-3 py-1 font-mono text-[0.62rem] ${toneClass("green")}`}>
                decision: {decisionPromote} promote
              </span>
              <span className={`rounded-full border px-3 py-1 font-mono text-[0.62rem] ${strictPromote === decisionPromote ? toneClass("green") : toneClass("yellow")}`}>
                strict: {strictPromote} promote
              </span>
            </div>
            {gapRatio !== null && (
              <span className="font-mono text-[0.64rem] text-white/42">
                gap ratio {(gapRatio * 100).toFixed(1)}%
                {gapRatio > 0.3 && (
                  <span className="ml-2 text-[var(--accent-warning)]">— CI 미달 신호 다수</span>
                )}
              </span>
            )}
            {alpha?.bootstrapConfig && (
              <span className="ml-auto rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.58rem] text-white/36">
                {stringField(alpha.bootstrapConfig as JsonObject, "method") || "circular-block"} · B={numberField(alpha.bootstrapConfig as JsonObject, "n_bootstrap") ?? "?"} · b={numberField(alpha.bootstrapConfig as JsonObject, "block_length") ?? "?"}
              </span>
            )}
          </div>
        </div>
      )}

      {overlayPromotionGate && (
        <div className="rounded-2xl border border-[var(--accent-green)]/22 bg-[var(--accent-green)]/6 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-green)]/82">
                Overlay gate · vol_regime_v2
              </p>
              <p className="mt-1 font-mono text-[0.68rem] leading-5 text-white/46">
                replayed 14d drift window passed the pilot promotion gate; strict CI gate remains visible separately.
              </p>
            </div>
            <span className={`w-fit rounded-full border px-3 py-1 font-mono text-[0.58rem] uppercase tracking-[0.12em] ${toneClass("green")}`}>
              pilot promoted
            </span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <MetricTile label="Hit rate" value={formatPercent(firstNumberField(overlayPromotionGate, ["rollingHitRate", "hit_rate"]), 1)} detail="rolling mean" />
            <MetricTile label="Coverage" value={formatPercent(firstNumberField(overlayPromotionGate, ["rollingCoverage", "coverage"]), 1)} detail="rolling mean" />
            <MetricTile label="p-value" value={formatNumber(firstNumberField(overlayPromotionGate, ["rollingPMedian", "pvalue"]), 4)} detail="median gate" />
            <MetricTile label="Records" value={formatNumber(firstNumberField(overlayPromotionGate, ["nRecords", "records"]), 0)} detail={`${promotedRows.length} promoted row`} />
          </div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Top signal hit rates</p>
          <div className="mt-4 space-y-3">
            {topSignals.length > 0 ? (
              topSignals.map((row) => {
                const hitRate = numberField(row, "hit_rate");
                const uplift = hitRate !== null && bestBaseline !== null ? hitRate - bestBaseline : null;
                const decision = typeof row.decision === "string" ? row.decision : undefined;
                const decisionStrict = typeof row.decision_strict === "string" ? row.decision_strict : undefined;
                const fdrQ = numberField(row, "fdr_q");
                return (
                  <SignalMetricRow
                    key={`${stringField(row, "predictor")}-${stringField(row, "return_col")}`}
                    label={formatFeatureLabel(stringField(row, "predictor"))}
                    value={formatPercent(hitRate, 1)}
                    detail={uplift === null ? "baseline n/a" : `uplift ${(uplift * 100).toFixed(1)}pp`}
                    ratio={hitRate}
                    tone={decision === "promote" ? "green" : uplift !== null && uplift < 0 ? "red" : "yellow"}
                    ciLower={numberField(row, "hit_rate_ci_lower")}
                    ciUpper={numberField(row, "hit_rate_ci_upper")}
                    decisionStrict={decisionStrict}
                    fdrQ={fdrQ}
                    isPromoted={row.promoted_from_research_rule === true}
                    promotionGate={isJsonObject(row.promotionGate) ? row.promotionGate : undefined}
                  />
                );
              })
            ) : (
              <EmptyPanel label="no horizon hit-rate data" />
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Backtest / walk-forward</p>
          <div className="mt-4 space-y-3">
            {horizonBacktest.slice(0, 4).map((row) => (
              <SignalMetricRow
                key={`${stringField(row, "predictor")}-${stringField(row, "return_col")}-bt`}
                label={formatFeatureLabel(stringField(row, "predictor"))}
                value={formatNumber(numberField(row, "sharpe_ratio"), 2)}
                detail={`alpha ${formatPercent(numberField(row, "alpha"), 2)}`}
                ratio={Math.min(Math.max((numberField(row, "sharpe_ratio") ?? 0) / 2, 0), 1)}
                tone={(numberField(row, "sharpe_ratio") ?? 0) > 0.5 ? "green" : "muted"}
                ciLower={typeof numberField(row, "sharpe_ci_lower") === "number" ? Math.min(Math.max((numberField(row, "sharpe_ci_lower") ?? 0) / 2, 0), 1) : null}
                ciUpper={typeof numberField(row, "sharpe_ci_upper") === "number" ? Math.min(Math.max((numberField(row, "sharpe_ci_upper") ?? 0) / 2, 0), 1) : null}
              />
            ))}
            <WalkForwardRows alpha={alpha} activeHorizon={activeHorizon} />
          </div>
        </div>
      </div>

      {/* Research rules section */}
      {researchRows.length > 0 && (
        <div className="rounded-2xl border border-purple-400/20 bg-purple-400/[0.04] p-4">
          <div className="flex items-center justify-between gap-4">
            <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-purple-400/80">
              Research rules · not yet in production gate
            </p>
            <span className="rounded-full border border-purple-400/20 bg-purple-400/8 px-3 py-1 font-mono text-[0.6rem] text-purple-400/70">
              {researchRows.length} signals
            </span>
          </div>
          <div className="mt-4 space-y-3">
            {researchRows.map((row) => {
              const hitRate = numberField(row, "hit_rate");
              const uplift = hitRate !== null && bestBaseline !== null ? hitRate - bestBaseline : null;
              return (
                <SignalMetricRow
                  key={`${stringField(row, "predictor")}-${stringField(row, "return_col")}-research`}
                  label={formatFeatureLabel(stringField(row, "predictor"))}
                  value={formatPercent(hitRate, 1)}
                  detail={uplift === null ? "baseline n/a" : `uplift ${(uplift * 100).toFixed(1)}pp`}
                  ratio={hitRate}
                  tone={uplift !== null && uplift > 0.02 ? "green" : uplift !== null && uplift < 0 ? "red" : "yellow"}
                  ciLower={numberField(row, "hit_rate_ci_lower")}
                  ciUpper={numberField(row, "hit_rate_ci_upper")}
                  decisionStrict={typeof row.decision_strict === "string" ? row.decision_strict : undefined}
                  fdrQ={numberField(row, "fdr_q")}
                  isResearch
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function WalkForwardRows({ alpha, activeHorizon }: { alpha?: AlphaSection; activeHorizon: string }) {
  const entries = objectEntries(alpha?.walkForwardHorizons);
  if (entries.length === 0) return null;

  return (
    <div className="border-t border-white/8 pt-3">
      {entries.map(([indexName, raw]) => {
        const horizonRecord = isJsonObject(raw) && isJsonObject(raw[activeHorizon]) ? raw[activeHorizon] : undefined;
        return (
          <SignalMetricRow
            key={`${indexName}-${activeHorizon}-wf`}
            label={`${indexName} walk-forward`}
            value={formatPercent(numberField(horizonRecord, "avg_hit_rate"), 1)}
            detail={`stability ${formatNumber(numberField(horizonRecord, "stability"), 2)}`}
            ratio={numberField(horizonRecord, "avg_hit_rate")}
            tone={(numberField(horizonRecord, "stability") ?? 0) >= 0.5 ? "green" : "yellow"}
          />
        );
      })}
    </div>
  );
}

function LegacyArtifactNotice({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="mb-4 rounded-2xl border border-[var(--accent-warning)]/24 bg-[var(--accent-warning)]/7 p-4">
      <p className="font-mono text-[0.66rem] uppercase tracking-[0.14em] text-[var(--accent-warning)]">
        {title}
      </p>
      <p className="mt-2 text-[0.76rem] leading-6 text-white/52">{detail}</p>
    </div>
  );
}

export function TargetDiagnosticsPanel({
  targets,
  diagnosticsReady,
}: {
  targets?: TargetsSection;
  diagnosticsReady: boolean;
}) {
  const diagnostics = targets?.diagnostics ?? {};
  const entries = objectEntries(diagnostics).filter(([, value]) => isJsonObject(value));
  const fixed = isJsonObject(diagnostics.btc_large_move_3d) ? diagnostics.btc_large_move_3d : undefined;
  const volAdjusted = isJsonObject(diagnostics.btc_large_move_3d_vol_adj) ? diagnostics.btc_large_move_3d_vol_adj : undefined;

  return (
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
        {!diagnosticsReady && (
          <LegacyArtifactNotice
            title="Target diagnostics are not published in latest.json"
            detail="The parquet contains fixed / vol-adjusted large move label diagnostics, but the current public artifact does not include target diagnostics."
          />
        )}
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          Target diagnostics
        </p>
        <p className="mt-2 font-mono text-[0.76rem] leading-6 text-white/40">
          Compare event rates across return targets and large-move labels. Labels that are too common create an illusion of easy prediction — inspect both fixed and vol-adjusted thresholds.
        </p>
        <div className="mt-5 space-y-4">
          <RatioRow label="fixed large move" value={formatPercent(numberField(fixed, "positive_rate"), 1)} ratio={numberField(fixed, "positive_rate")} />
          <RatioRow label="vol-adjusted move" value={formatPercent(numberField(volAdjusted, "positive_rate"), 1)} ratio={numberField(volAdjusted, "positive_rate")} />
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
        <div className="grid gap-3 md:grid-cols-2">
          {entries.length > 0 ? (
            entries.map(([target, value]) => {
              const record = value as JsonObject;
              return (
                <article key={target} className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                  <p className="font-mono text-[0.62rem] uppercase tracking-[0.14em] text-white/30">{target}</p>
                  <p className="mt-2 text-[0.92rem] font-semibold text-white/84">
                    {numberField(record, "positive_rate") !== null
                      ? formatPercent(numberField(record, "positive_rate"), 1)
                      : formatNumber(numberField(record, "mean"), 4)}
                  </p>
                  <p className="mt-2 font-mono text-[0.64rem] leading-5 text-white/36">
                    valid {formatNumber(numberField(record, "valid_rows"))} · null {formatPercent(numberField(record, "null_ratio"), 1)}
                  </p>
                </article>
              );
            })
          ) : (
            <EmptyPanel label="no target diagnostics" />
          )}
        </div>
      </div>
    </div>
  );
}

export function StationarityPanel({
  adf,
  diagnosticsReady,
}: {
  adf?: JsonObject;
  diagnosticsReady: boolean;
}) {
  const rows = objectEntries(adf).filter(([, value]) => isJsonObject(value)).slice(0, 12);

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
      {!diagnosticsReady && (
        <LegacyArtifactNotice
          title="Stationarity diagnostics pending"
          detail="ADF / stationarity metadata exists in the parquet sentiment_join_stats but is not included in the legacy public artifact."
        />
      )}
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            Stationarity gate
          </p>
          <p className="mt-2 max-w-2xl font-mono text-[0.76rem] leading-6 text-white/40">
            Time-series tests assume stationarity. Weak ADF results cause skips or reduce confidence in causality estimates — trace root cause here.
          </p>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/38">
          {objectEntries(adf).length} series
        </span>
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[640px] border-separate border-spacing-y-2 text-left">
          <thead>
            <tr className="font-mono text-[0.6rem] uppercase tracking-[0.14em] text-white/28">
              <th className="px-3 py-2">series</th>
              <th className="px-3 py-2">p-value</th>
              <th className="px-3 py-2">stat</th>
              <th className="px-3 py-2">status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length > 0 ? (
              rows.map(([series, raw]) => {
                const row = raw as JsonObject;
                const pvalue = numberField(row, "pvalue") ?? numberField(row, "p_value");
                const stat = numberField(row, "adf_stat") ?? numberField(row, "statistic");
                const stationaryRaw = row.stationary;
                const stationary = typeof stationaryRaw === "boolean" ? stationaryRaw : pvalue !== null ? pvalue < 0.05 : null;
                return (
                  <tr key={series} className="rounded-2xl bg-white/[0.025] text-[0.76rem] text-white/68">
                    <td className="rounded-l-2xl px-3 py-3 font-semibold">{formatFeatureLabel(series)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums">{formatNumber(pvalue, 4)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums">{formatNumber(stat, 3)}</td>
                    <td className="rounded-r-2xl px-3 py-3">
                      <span className={`rounded-full border px-2.5 py-1 font-mono text-[0.6rem] uppercase tracking-[0.12em] ${stationary ? toneClass("green") : toneClass("yellow")}`}>
                        {stationary ? "stationary" : "watch"}
                      </span>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={4}>
                  <EmptyPanel label="No stationarity metadata" />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RawMetadataExplorer({
  rawStats,
  diagnosticsReady,
}: {
  rawStats?: JsonObject;
  diagnosticsReady: boolean;
}) {
  const payload = rawStats ?? {};
  const keyCount = objectEntries(payload).length;
  return (
    <details className="group rounded-3xl border border-white/10 bg-black/30 p-4 open:bg-black/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-2xl px-1 py-1">
        <span>
          <span className="block font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            Raw parquet metadata
          </span>
          <span className="mt-1 block font-mono text-[0.74rem] text-white/40">
            {diagnosticsReady
              ? `sentiment_join_stats · ${keyCount} keys · ground truth view`
              : "latest.json is legacy v1 — rawStats not yet published"}
          </span>
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/38 group-open:text-[var(--accent-primary)]">
          expand
        </span>
      </summary>
      {diagnosticsReady ? (
        <pre className="mt-4 max-h-[560px] overflow-auto rounded-2xl border border-white/8 bg-[#030303] p-4 text-[0.68rem] leading-5 text-white/54">
          {JSON.stringify(payload, null, 2)}
        </pre>
      ) : (
        <div className="mt-4">
          <LegacyArtifactNotice
            title="Raw metadata unavailable in the public artifact"
            detail="The full parquet sentiment_join_stats will appear here once the next v2 sentiment artifact is generated and published."
          />
        </div>
      )}
    </details>
  );
}

function MetricTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-3">
      <p className="font-mono text-[0.58rem] uppercase tracking-[0.14em] text-white/28">{label}</p>
      <p className="numeric-sm mt-1 text-white/78">{value}</p>
      <p className="mt-1 font-mono text-[0.62rem] text-white/32">{detail}</p>
    </div>
  );
}

function RatioRow({
  label,
  value,
  ratio,
}: {
  label: string;
  value: string;
  ratio: number | null;
}) {
  const width = typeof ratio === "number" && Number.isFinite(ratio) ? Math.min(Math.max(ratio * 100, 4), 100) : 4;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-3 font-mono text-[0.64rem]">
        <span className="uppercase tracking-[0.12em] text-white/38">{label}</span>
        <span className="text-white/64">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/8">
        <div
          className="h-full rounded-full bg-[var(--accent-green)] shadow-[0_0_18px_rgba(14,203,129,0.22)]"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

function SignalMetricRow({
  label,
  value,
  detail,
  ratio,
  tone,
  ciLower,
  ciUpper,
  decisionStrict,
  fdrQ,
  isResearch,
  isPromoted,
  promotionGate,
}: {
  label: string;
  value: string;
  detail: string;
  ratio: number | null;
  tone: Tone;
  ciLower?: number | null;
  ciUpper?: number | null;
  decisionStrict?: string;
  fdrQ?: number | null;
  isResearch?: boolean;
  isPromoted?: boolean;
  promotionGate?: JsonObject;
}) {
  const barWidth = typeof ratio === "number" && Number.isFinite(ratio) ? Math.min(Math.max(ratio * 100, 4), 100) : 4;
  const loPct = typeof ciLower === "number" && Number.isFinite(ciLower) ? Math.min(Math.max(ciLower * 100, 0), 100) : null;
  const hiPct = typeof ciUpper === "number" && Number.isFinite(ciUpper) ? Math.min(Math.max(ciUpper * 100, 0), 100) : null;
  const hasCI = loPct !== null && hiPct !== null;
  const gatePvalue = firstNumberField(promotionGate, ["rollingPMedian", "pvalue"]);
  return (
    <article className="rounded-2xl border border-white/8 bg-white/[0.025] p-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-[0.82rem] font-semibold text-white/82">{label}</p>
            {isResearch && (
              <span className="shrink-0 rounded-full border border-purple-400/30 bg-purple-400/8 px-2 py-0.5 font-mono text-[0.54rem] uppercase tracking-[0.1em] text-purple-400/80">
                research
              </span>
            )}
            {isPromoted && (
              <span className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[0.54rem] uppercase tracking-[0.1em] ${toneClass("green")}`}>
                promoted
              </span>
            )}
          </div>
          <div className="mt-1 flex items-center gap-2 font-mono text-[0.62rem] text-white/34">
            <span>{detail}</span>
            {typeof fdrQ === "number" && (
              <span className={fdrQ <= 0.10 ? "text-[var(--accent-green)]/70" : "text-[var(--accent-warning)]/70"}>
                q={fdrQ.toFixed(3)}
              </span>
            )}
            {gatePvalue !== null && (
              <span className="text-[var(--accent-green)]/70">gate p={gatePvalue.toFixed(3)}</span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {decisionStrict !== undefined && (
            <span
              className={`rounded-full border px-2 py-0.5 font-mono text-[0.56rem] uppercase tracking-[0.1em] ${
                decisionStrict === "promote" ? toneClass("green") : toneClass("muted")
              }`}
              title="decision_strict (CI hard-separation + FDR q≤0.10)"
            >
              strict
            </span>
          )}
          <span className={`rounded-full border px-2.5 py-1 font-mono text-[0.62rem] ${toneClass(tone)}`}>
            {value}
          </span>
        </div>
      </div>
      <div className="relative mt-3 h-1.5 rounded-full bg-white/8">
        <div
          className={`absolute h-full rounded-full ${
            tone === "green"
              ? "bg-[var(--accent-green)]"
              : tone === "red"
                ? "bg-[var(--accent-down)]"
                : "bg-white/50"
          }`}
          style={{ width: `${barWidth}%` }}
        />
        {hasCI && (
          <>
            <div
              className="absolute top-0 h-full rounded-full bg-white/20"
              style={{ left: `${loPct}%`, width: `${(hiPct ?? 0) - (loPct ?? 0)}%` }}
            />
            <div className="absolute top-0 h-full w-px bg-white/60" style={{ left: `${loPct}%` }} />
            <div className="absolute top-0 h-full w-px bg-white/60" style={{ left: `${hiPct}%` }} />
          </>
        )}
      </div>
    </article>
  );
}

function EmptyPanel({ label }: { label: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.015] p-4">
      <p className="font-mono text-[0.68rem] text-white/34">{label}</p>
    </div>
  );
}
