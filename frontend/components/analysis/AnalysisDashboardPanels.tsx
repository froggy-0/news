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
  return value.toLocaleString("ko-KR", {
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
  if (tone === "green") return "border-[var(--accent-green)]/24 bg-[var(--accent-green)]/7 text-[var(--accent-green)]";
  if (tone === "yellow") return "border-[var(--accent-warning)]/28 bg-[var(--accent-warning)]/8 text-[var(--accent-warning)]";
  if (tone === "red") return "border-[var(--accent-down)]/28 bg-[var(--accent-down)]/8 text-[var(--accent-down)]";
  if (tone === "cyan") return "border-[var(--accent-primary)]/26 bg-[var(--accent-primary)]/8 text-[var(--accent-primary)]";
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

export function AnalysisOverviewDeck({ artifact }: { artifact: SentimentInsightArtifact }) {
  const summary = artifact.summary;
  const rows = artifact.dataQuality?.rows;
  const significantCount =
    summary?.significantGrangerCount ?? artifact.granger.results.filter((row) => row.significant).length;
  const skipCount = artifact.granger.skips?.length ?? 0;
  const rawKeyCount = objectEntries(artifact.rawStats).length;
  const outlierTone = statusToneFromRatio(rows?.outlierFilteredRatio, 0.1);

  return (
    <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6" aria-label="분석 리포트 핵심 상태">
      <OverviewCard
        icon={<ShieldCheck className="h-4 w-4" />}
        label="Run State"
        value={artifact.schemaVersion ?? "v1"}
        caption={`${artifact.runId} · ${artifact.referenceDate}`}
        tone="cyan"
      />
      <OverviewCard
        icon={<Database className="h-4 w-4" />}
        label="Rows"
        value={formatNumber(rows?.afterOutlierFilter ?? summary?.rowsAfterOutlierFilter)}
        caption={`raw ${formatNumber(rows?.beforeOutlierFilter ?? summary?.rowsBeforeOutlierFilter)} · masked ${formatPercent(rows?.outlierFilteredRatio, 1)}`}
        tone={outlierTone}
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
        value={`${summary?.alphaCandidateCount ?? artifact.alpha?.hitRates.length ?? 0} signals`}
        caption={`${summary?.horizonMetricCount ?? objectEntries(artifact.alpha?.horizonMetrics).length} horizons · baseline linked`}
        tone="cyan"
      />
      <OverviewCard
        icon={<Target className="h-4 w-4" />}
        label="Targets"
        value={`${summary?.targetCount ?? objectEntries(artifact.targets?.diagnostics).length}`}
        caption="fixed + volatility adjusted labels"
        tone="green"
      />
      <OverviewCard
        icon={<TableProperties className="h-4 w-4" />}
        label="Raw Metadata"
        value={`${rawKeyCount} keys`}
        caption="parquet sentiment_join_stats"
        tone={rawKeyCount > 0 ? "green" : "muted"}
      />
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

export function DataQualityMatrix({ dataQuality }: { dataQuality?: DataQualitySection }) {
  const sourceEntries = objectEntries(dataQuality?.structuredSources);
  const ffillEntries = objectEntries(dataQuality?.ffillBreakdown);
  const exclusionEntries = objectEntries(dataQuality?.exclusionCounts);
  const rows = dataQuality?.rows;

  return (
    <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
      <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
              데이터 품질 매트릭스
            </p>
            <p className="mt-2 max-w-2xl text-[0.82rem] leading-6 text-white/48">
              분석 결과보다 먼저 확인해야 하는 입력 데이터 상태입니다. source, ffill, outlier masking을
              한 화면에서 확인합니다.
            </p>
          </div>
          <div className="hidden rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/38 md:block">
            coverage first
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <MetricTile label="사용 행" value={formatNumber(rows?.afterOutlierFilter)} detail={`원본 ${formatNumber(rows?.beforeOutlierFilter)}`} />
          <MetricTile label="마스킹" value={formatNumber(rows?.outlierFilteredCount)} detail={formatPercent(rows?.outlierFilteredRatio, 2)} />
          <MetricTile label="제외 사유" value={`${exclusionEntries.length}`} detail="feature exclusion groups" />
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
            <EmptyPanel label="source metadata 없음" />
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
              <EmptyPanel label="ffill breakdown 없음" />
            )}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Exclusions</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {exclusionEntries.length > 0 ? (
              exclusionEntries.map(([name, value]) => (
                <span key={name} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.64rem] text-white/54">
                  {name}: {formatValue(value)}
                </span>
              ))
            ) : (
              <span className="font-mono text-[0.68rem] text-white/34">제외 카운트 없음</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function AlphaValidationBoard({ alpha, summary }: { alpha?: AlphaSection; summary?: ArtifactSummary }) {
  const horizons = useMemo(
    () => objectEntries(alpha?.horizonMetrics).map(([key]) => key).sort((a, b) => Number(a) - Number(b)),
    [alpha?.horizonMetrics],
  );
  const [activeHorizon, setActiveHorizon] = useState(horizons[0] ?? "1");
  const horizonRaw = alpha?.horizonMetrics?.[activeHorizon];
  const horizon = isJsonObject(horizonRaw) ? horizonRaw : undefined;
  const horizonHitRates = objectArray(isJsonObject(horizon) && Array.isArray(horizon.hit_rates) ? horizon.hit_rates : alpha?.hitRates);
  const horizonBacktest = objectArray(isJsonObject(horizon) && Array.isArray(horizon.backtest) ? horizon.backtest : alpha?.backtest);
  const baselineRaw = alpha?.baselineMetrics?.[activeHorizon];
  const baselines = isJsonObject(baselineRaw) ? baselineRaw : undefined;
  const bestBaseline = bestBaselineHitRate(baselines);
  const topSignals = [...horizonHitRates]
    .sort((a, b) => (numberField(b, "hit_rate") ?? -1) - (numberField(a, "hit_rate") ?? -1))
    .slice(0, 5);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            Alpha validation
          </p>
          <p className="mt-2 max-w-2xl text-[0.82rem] leading-6 text-white/48">
            후보 신호는 baseline 대비 uplift가 있어야 승격할 수 있습니다. 동시상관이 아니라 1/3/7일 horizon 기준
            선행 성능을 봅니다.
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
                  ? "bg-white/12 text-white shadow-[0_0_22px_rgba(0,255,255,0.12)]"
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
        <MetricTile label="후보 신호" value={`${summary?.alphaCandidateCount ?? alpha?.hitRates.length ?? 0}`} detail="lag-only predictors" />
        <MetricTile label="Horizon" value={`${activeHorizon}일`} detail={stringField(horizon, "return_col") || "return target"} />
        <MetricTile label="최고 baseline" value={formatPercent(bestBaseline, 1)} detail="best reference model" />
        <MetricTile label="walk-forward" value={`${objectEntries(alpha?.walkForwardHorizons).length}`} detail="full/core folds" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-white/58">Top signal hit rates</p>
          <div className="mt-4 space-y-3">
            {topSignals.length > 0 ? (
              topSignals.map((row) => {
                const hitRate = numberField(row, "hit_rate");
                const uplift = hitRate !== null && bestBaseline !== null ? hitRate - bestBaseline : null;
                return (
                  <SignalMetricRow
                    key={`${stringField(row, "predictor")}-${stringField(row, "return_col")}`}
                    label={formatFeatureLabel(stringField(row, "predictor"))}
                    value={formatPercent(hitRate, 1)}
                    detail={uplift === null ? "baseline n/a" : `uplift ${(uplift * 100).toFixed(1)}pp`}
                    ratio={hitRate}
                    tone={uplift !== null && uplift > 0.02 ? "green" : uplift !== null && uplift < 0 ? "red" : "yellow"}
                  />
                );
              })
            ) : (
              <EmptyPanel label="horizon hit-rate 없음" />
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
              />
            ))}
            <WalkForwardRows alpha={alpha} activeHorizon={activeHorizon} />
          </div>
        </div>
      </div>
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

export function TargetDiagnosticsPanel({ targets }: { targets?: TargetsSection }) {
  const diagnostics = targets?.diagnostics ?? {};
  const entries = objectEntries(diagnostics).filter(([, value]) => isJsonObject(value));
  const fixed = isJsonObject(diagnostics.btc_large_move_3d) ? diagnostics.btc_large_move_3d : undefined;
  const volAdjusted = isJsonObject(diagnostics.btc_large_move_3d_vol_adj) ? diagnostics.btc_large_move_3d_vol_adj : undefined;

  return (
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          Target diagnostics
        </p>
        <p className="mt-2 text-[0.82rem] leading-6 text-white/48">
          수익률 target과 large move label의 이벤트 비율을 비교합니다. label이 너무 흔하면 예측 문제가
          쉬워 보이는 착시가 생깁니다.
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
                  <p className="mt-2 font-mono text-[0.64rem] leading-5 text-white/38">
                    valid {formatNumber(numberField(record, "valid_rows"))} · null {formatPercent(numberField(record, "null_ratio"), 1)}
                  </p>
                </article>
              );
            })
          ) : (
            <EmptyPanel label="target diagnostics 없음" />
          )}
        </div>
      </div>
    </div>
  );
}

export function StationarityPanel({ adf }: { adf?: JsonObject }) {
  const rows = objectEntries(adf).filter(([, value]) => isJsonObject(value)).slice(0, 12);

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            Stationarity gate
          </p>
          <p className="mt-2 max-w-2xl text-[0.82rem] leading-6 text-white/48">
            시계열 검정은 정상성 조건이 흔들리면 해석이 약해집니다. ADF 결과를 함께 노출해 skip과
            유의성의 원인을 추적합니다.
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
                      <span className={`rounded-full border px-2.5 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] ${stationary ? toneClass("green") : toneClass("yellow")}`}>
                        {stationary ? "stationary" : "watch"}
                      </span>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={4}>
                  <EmptyPanel label="stationarity metadata 없음" />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RawMetadataExplorer({ rawStats }: { rawStats?: JsonObject }) {
  const payload = rawStats ?? {};
  const keyCount = objectEntries(payload).length;
  return (
    <details className="group rounded-3xl border border-white/10 bg-black/30 p-4 open:bg-black/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-2xl px-1 py-1">
        <span>
          <span className="block font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            Raw parquet metadata
          </span>
          <span className="mt-1 block text-[0.82rem] text-white/46">
            sentiment_join_stats 원본 {keyCount}개 key를 그대로 확인합니다.
          </span>
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/38 group-open:text-[var(--accent-primary)]">
          expand
        </span>
      </summary>
      <pre className="mt-4 max-h-[560px] overflow-auto rounded-2xl border border-white/8 bg-[#030303] p-4 text-[0.68rem] leading-5 text-white/58">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </details>
  );
}

function MetricTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-3">
      <p className="font-mono text-[0.58rem] uppercase tracking-[0.14em] text-white/28">{label}</p>
      <p className="mt-1 font-mono text-[0.86rem] tabular-nums text-white/78">{value}</p>
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
          className="h-full rounded-full bg-[var(--accent-primary)] shadow-[0_0_18px_rgba(0,255,255,0.22)]"
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
}: {
  label: string;
  value: string;
  detail: string;
  ratio: number | null;
  tone: Tone;
}) {
  const width = typeof ratio === "number" && Number.isFinite(ratio) ? Math.min(Math.max(ratio * 100, 4), 100) : 4;
  return (
    <article className="rounded-2xl border border-white/8 bg-white/[0.025] p-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-[0.82rem] font-semibold text-white/82">{label}</p>
          <p className="mt-1 font-mono text-[0.62rem] text-white/34">{detail}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-2.5 py-1 font-mono text-[0.62rem] ${toneClass(tone)}`}>
          {value}
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full bg-white/70" style={{ width: `${width}%` }} />
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
