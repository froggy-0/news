"use client";

import React, { useMemo, useState } from "react";
import type { AlphaSection, GrangerSection, JsonObject, JsonValue } from "@schema/analysis.types";
import { formatFeatureLabel } from "@/lib/analysis-derive";

// ─── helpers ────────────────────────────────────────────────────────────────

function num(v: JsonValue | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function str(v: JsonValue | undefined): string {
  return typeof v === "string" ? v : "";
}

function pctLabel(v: number | null, digits = 1): string {
  if (v === null) return "n/a";
  return `${(v * 100).toFixed(digits)}%`;
}

// Short feature label for cramped spaces
function shortLabel(feature: string): string {
  const label = formatFeatureLabel(feature);
  return label.length > 14 ? label.slice(0, 13) + "…" : label;
}

// ─── Baseline CI Chart ───────────────────────────────────────────────────────
//
// Dot-and-whisker chart: 5 baselines × T+7 hit rate with 95% bootstrap CI.

const BASELINE_DISPLAY: Record<string, { label: string; order: number }> = {
  vol_regime_v2:  { label: "Vol Regime v2",    order: 0 },
  vol_regime:     { label: "Vol Regime",        order: 1 },
  always_up:      { label: "Always Long",       order: 2 },
  btc_momo_20d:   { label: "BTC Momentum 20d", order: 3 },
  fng_contrarian: { label: "F&G Contrarian",   order: 4 },
};

type BEntry = {
  name: string;
  label: string;
  hitRate: number;
  ciLo: number | null;
  ciHi: number | null;
  sharpe: number;
  isBest: boolean;
};

export function BaselineCIChart({ alpha }: { alpha?: AlphaSection }) {
  const baselines = useMemo<BEntry[]>(() => {
    const raw = alpha?.baselineMetrics?.["7"];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];

    const entries: BEntry[] = Object.entries(raw as JsonObject)
      .map(([name, data]) => {
        const d = data as JsonObject;
        const ciLo = num(d.hit_rate_ci_lower);
        const ciHi = num(d.hit_rate_ci_upper);
        return {
          name,
          label: BASELINE_DISPLAY[name]?.label ?? name,
          hitRate: num(d.hit_rate) ?? 0,
          ciLo: ciLo !== null && ciLo > 0 ? ciLo : null,
          ciHi: ciHi !== null && ciHi > 0 ? ciHi : null,
          sharpe:  num(d.sharpe) ?? 0,
          isBest:  false,
        };
      })
      .sort((a, b) => (BASELINE_DISPLAY[a.name]?.order ?? 99) - (BASELINE_DISPLAY[b.name]?.order ?? 99));

    const bestIdx = entries.reduce((bi, e, i) => (e.hitRate > entries[bi].hitRate ? i : bi), 0);
    if (entries[bestIdx]) entries[bestIdx].isBest = true;
    return entries;
  }, [alpha]);

  if (baselines.length === 0) {
    return <EmptyChart label="No baseline data for horizon 7" />;
  }

  const hasCI = baselines.some(b => b.ciLo !== null && b.ciHi !== null);
  const allVals = baselines.flatMap(b => [b.ciLo ?? b.hitRate, b.ciHi ?? b.hitRate, b.hitRate]);
  const minV = Math.min(...allVals, 0.40) - 0.02;
  const maxV = Math.max(...allVals, 0.70) + 0.02;
  const span = maxV - minV;

  // percent position along chart width
  const toX = (v: number) => Math.min(100, Math.max(0, ((v - minV) / span) * 100));

  // tick values for x-axis
  const ticks = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70].filter(t => t >= minV && t <= maxV);

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <div className="mb-1">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          기본 전략 비교 — 7일 적중률
        </p>
      </div>
      <p className="mb-6 font-mono text-[0.68rem] leading-5 text-white/38">
        {hasCI
          ? "점 = 부트스트랩 평균 · 수염 = 95% CI (B=1000, block=14) · 50% 기준선 대비"
          : "점 = 적중률 · CI 범위 없음"}
      </p>

      {/* chart area */}
      <div className="relative select-none">
        {/* vertical reference at 50% */}
        <div
          className="pointer-events-none absolute inset-y-0 w-px border-l border-dashed border-white/18"
          style={{ left: `${toX(0.5)}%` }}
          aria-hidden
        />

        <div className="space-y-5">
          {baselines.map((b) => {
            const dotX  = toX(b.hitRate);
            const loX   = b.ciLo !== null ? toX(b.ciLo) : null;
            const hiX   = b.ciHi !== null ? toX(b.ciHi) : null;
            const spanW = loX !== null && hiX !== null ? Math.max(hiX - loX, 0.4) : 0;

            return (
              <div key={b.name} className="group">
                {/* label row */}
                <div className="mb-1.5 flex items-center justify-between gap-4">
                  <span
                    className={`font-mono text-[0.72rem] transition-colors ${
                      b.isBest ? "text-[var(--accent-green)]" : "text-white/58 group-hover:text-white/76"
                    }`}
                  >
                    {b.label}
                  </span>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className="font-mono text-[0.60rem] tabular-nums text-white/30">
                      Sharpe {b.sharpe.toFixed(2)}
                    </span>
                    <span
                      className={`font-mono text-[0.76rem] font-semibold tabular-nums ${
                        b.isBest ? "text-[var(--accent-green)]" : "text-white/68"
                      }`}
                    >
                      {pctLabel(b.hitRate)}
                    </span>
                  </div>
                </div>

                {/* track + whisker + dot */}
                <div className="relative h-8">
                  {/* track */}
                  <div className="absolute inset-y-[15px] w-full rounded-full bg-white/5" />

                  {/* CI band — only when CI bounds are available */}
                  {loX !== null && hiX !== null && spanW > 0 && (
                    <>
                      <div
                        className={`absolute inset-y-[11px] rounded-full transition-opacity ${
                          b.isBest ? "bg-[var(--accent-green)]/22" : "bg-white/8"
                        }`}
                        style={{ left: `${loX}%`, width: `${spanW}%` }}
                      />
                      <div
                        className="absolute inset-y-[9px] w-px rounded-full bg-white/28"
                        style={{ left: `${loX}%` }}
                      />
                      <div
                        className="absolute inset-y-[9px] w-px rounded-full bg-white/28"
                        style={{ left: `${hiX}%` }}
                      />
                    </>
                  )}

                  {/* dot */}
                  <div
                    className={`absolute top-1/2 h-[14px] w-[14px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition-all duration-200 group-hover:scale-125 ${
                      b.isBest
                        ? "border-[var(--accent-green)] bg-[var(--accent-green)]/40 shadow-[0_0_14px_rgba(14,203,129,0.40)]"
                        : "border-white/46 bg-black/70"
                    }`}
                    style={{ left: `${dotX}%` }}
                    role="img"
                    aria-label={`${b.label}: ${pctLabel(b.hitRate)} [${pctLabel(b.ciLo)} – ${pctLabel(b.ciHi)}]`}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* x-axis ticks */}
        <div className="relative mt-4">
          {ticks.map((t) => (
            <span
              key={t}
              className="absolute -translate-x-1/2 font-mono text-[0.56rem] text-white/22"
              style={{ left: `${toX(t)}%` }}
            >
              {(t * 100).toFixed(0)}%
            </span>
          ))}
          <div className="h-3" />
        </div>
      </div>

      {/* 50% label */}
      <p className="mt-1 font-mono text-[0.58rem] text-white/20" style={{ paddingLeft: `${toX(0.5)}%` }}>
        50% baseline
      </p>
    </div>
  );
}

// ─── Granger Causality Heatmap ───────────────────────────────────────────────
//
// Matrix: predictor (row) × target (col), colored by FDR-adjusted p-value.
// Only optimalLag results are shown.

type HeatCell = {
  pAdj: number | null;
  significant: boolean;
  lag: number | null;
  direction: "forward" | "reverse";
};

const TARGET_DISPLAY_ORDER = [
  "btc_log_return",
  "fng_value",
  "news_sentiment_mean",
  "etf_net_inflow_usd",
  "funding_rate_zscore_30d",
  "long_short_ratio_zscore_30d",
  "volume_change_pct",
];

const PREDICTOR_DISPLAY_ORDER = [
  "news_sentiment_mean",
  "sentiment_momentum",
  "fng_value",
  "fng_change_1d",
  "btc_log_return",
  "funding_rate_zscore_30d",
  "long_short_ratio_zscore_30d",
  "etf_net_inflow_usd",
  "btc_taker_imbalance_zscore_30d",
  "oi_change_pct",
  "volume_change_pct",
  "usdkrw_log_return",
  "etf_net_inflow_usd_log1p",
];

export function GrangerHeatmap({ granger }: { granger: GrangerSection }) {
  const { predictors, targets, matrix } = useMemo(() => {
    const optimal = granger.results.filter((r) => r.optimalLag);

    const predSet  = new Set(optimal.map((r) => r.predictor));
    const tgtSet   = new Set(optimal.map((r) => r.target));

    const preds = PREDICTOR_DISPLAY_ORDER.filter((p) => predSet.has(p));
    const tgts  = TARGET_DISPLAY_ORDER.filter((t) => tgtSet.has(t));

    const mat: Record<string, Record<string, HeatCell>> = {};
    for (const p of preds) {
      mat[p] = {};
      for (const t of tgts) {
        mat[p][t] = { pAdj: null, significant: false, lag: null, direction: "forward" };
      }
    }
    for (const r of optimal) {
      const cell = mat[r.predictor]?.[r.target];
      if (cell) {
        cell.pAdj       = r.pvalueAdjusted;
        cell.significant = r.significant;
        cell.lag         = r.lag;
        cell.direction   = r.direction;
      }
    }
    return { predictors: preds, targets: tgts, matrix: mat };
  }, [granger]);

  function cellBg(cell: HeatCell): string {
    if (!cell.pAdj || !cell.significant) return "bg-white/[0.03] border-white/6";
    if (cell.pAdj < 0.005) return "bg-[var(--accent-green)]/38 border-[var(--accent-green)]/50";
    if (cell.pAdj < 0.01)  return "bg-[var(--accent-green)]/28 border-[var(--accent-green)]/38";
    if (cell.pAdj < 0.05)  return "bg-[var(--accent-green)]/14 border-[var(--accent-green)]/22";
    return "bg-[var(--accent-green)]/6 border-[var(--accent-green)]/14";
  }

  function cellText(cell: HeatCell): string {
    if (!cell.significant) return "text-white/18";
    if (cell.pAdj !== null && cell.pAdj < 0.01) return "text-[var(--accent-green)]";
    return "text-[var(--accent-green)]/74";
  }

  if (predictors.length === 0 || targets.length === 0) {
    return <EmptyChart label="No Granger results" />;
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <div className="mb-1">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          인과관계 매트릭스 — FDR-BH 검정
        </p>
      </div>
      <p className="mb-6 font-mono text-[0.68rem] leading-5 text-white/38">
        행 → 열 방향 · 최적 lag 기준 · {granger.correction.nTests}개 검정 · → 순방향 · ← 역방향
      </p>

      <div className="overflow-x-auto">
        <div className="min-w-max">
          {/* header row */}
          <div className="mb-1 flex gap-1 pl-[136px]">
            {targets.map((t) => (
              <div
                key={t}
                className="flex h-9 w-[88px] items-center justify-center text-center font-mono text-[0.52rem] uppercase leading-3 tracking-[0.07em] text-white/30"
              >
                {shortLabel(t)}
              </div>
            ))}
          </div>

          {/* data rows */}
          {predictors.map((pred) => (
            <div key={pred} className="mb-1 flex items-center gap-1">
              <div className="w-[132px] pr-3 text-right font-mono text-[0.60rem] leading-4 text-white/48">
                {shortLabel(pred)}
              </div>
              {targets.map((tgt) => {
                const cell = matrix[pred]?.[tgt] ?? {
                  pAdj: null, significant: false, lag: null, direction: "forward" as const,
                };
                const isEmpty = cell.pAdj === null;
                return (
                  <div
                    key={tgt}
                    className={`flex h-10 w-[88px] flex-col items-center justify-center gap-px rounded-lg border transition-all duration-150 hover:brightness-125 ${
                      isEmpty ? "border-white/5 bg-transparent" : cellBg(cell)
                    }`}
                    title={
                      isEmpty
                        ? `${pred} → ${tgt}: no result`
                        : `${pred} → ${tgt} | lag=${cell.lag} | p_adj=${cell.pAdj?.toFixed(4)}`
                    }
                  >
                    {isEmpty ? (
                      <span className="font-mono text-[0.52rem] text-white/12">—</span>
                    ) : (
                      <>
                        <span className={`font-mono text-[0.60rem] font-semibold tabular-nums ${cellText(cell)}`}>
                          {cell.pAdj !== null ? (cell.pAdj < 0.001 ? "<.001" : cell.pAdj.toFixed(3)) : "—"}
                        </span>
                        <span className="font-mono text-[0.50rem] text-white/26">
                          {cell.direction === "forward" ? "→" : "←"} L{cell.lag}
                        </span>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* legend */}
      <div className="mt-5 flex flex-wrap items-center gap-5">
        {[
          { bg: "bg-[var(--accent-green)]/38", label: "p < 0.005" },
          { bg: "bg-[var(--accent-green)]/28", label: "p < 0.01" },
          { bg: "bg-[var(--accent-green)]/14", label: "p < 0.05" },
          { bg: "bg-white/[0.03]",              label: "not significant" },
        ].map(({ bg, label }) => (
          <div key={label} className="flex items-center gap-2">
            <div className={`h-3 w-7 rounded-sm border border-white/10 ${bg}`} />
            <span className="font-mono text-[0.58rem] text-white/36">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Walk-Forward Timeseries ─────────────────────────────────────────────────
//
// SVG line chart: hit rate per out-of-sample fold (Core vs Full PCA index).

type FoldPoint = {
  fold: number;
  testStart: string;
  hitRate: number;
  cumReturn: number;
};

function parseFolds(raw: unknown): FoldPoint[] {
  if (!Array.isArray(raw)) return [];
  return (raw as JsonObject[]).map((f) => ({
    fold:       typeof f.fold === "number" ? f.fold : 0,
    testStart:  typeof f.test_start === "string" ? f.test_start.slice(0, 7) : "",
    hitRate:    typeof f.hit_rate === "number" ? f.hit_rate : 0,
    cumReturn:  typeof f.cumulative_return === "number" ? f.cumulative_return : 0,
  }));
}

export function WalkForwardTimeseries({
  alpha,
  walkForward1d,
}: {
  alpha?: AlphaSection;
  walkForward1d?: JsonObject;
}) {
  const [horizon, setHorizon] = useState<"7d" | "1d">("7d");
  const has1d = !!walkForward1d;

  const wf7 = alpha?.walkForward as JsonObject | undefined;
  const activeWf = horizon === "7d" ? wf7 : walkForward1d;

  const coreFolds = useMemo(() => parseFolds((activeWf?.core as JsonObject)?.folds), [activeWf]);
  const fullFolds = useMemo(() => parseFolds((activeWf?.full as JsonObject)?.folds), [activeWf]);

  const avgCore = num((activeWf?.core as JsonObject)?.avg_hit_rate);
  const avgFull = num((activeWf?.full as JsonObject)?.avg_hit_rate);

  const avg7Core = num((wf7?.core as JsonObject)?.avg_hit_rate);
  const avg1Core = has1d ? num((walkForward1d?.core as JsonObject)?.avg_hit_rate) : null;

  if (coreFolds.length === 0 && fullFolds.length === 0) {
    return <EmptyChart label="No walk-forward fold data" />;
  }

  const allFolds  = [...coreFolds, ...fullFolds];
  const allRates  = allFolds.map((f) => f.hitRate);
  const minHR     = Math.max(0.20, Math.min(...allRates) - 0.05);
  const maxHR     = Math.min(0.95, Math.max(...allRates) + 0.05);
  const nFolds    = Math.max(coreFolds.length, fullFolds.length);

  const W = 560, H = 200, PX = 44, PY = 20;
  const innerW = W - PX * 2;
  const innerH = H - PY * 2;

  const px = (fold: number) => PX + (nFolds > 1 ? (fold / (nFolds - 1)) * innerW : innerW / 2);
  const py = (hr: number)   => PY + ((maxHR - Math.min(Math.max(hr, minHR), maxHR)) / (maxHR - minHR)) * innerH;

  function polyline(pts: FoldPoint[], stroke: string): React.ReactNode {
    if (pts.length < 2) return null;
    const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${px(p.fold).toFixed(1)},${py(p.hitRate).toFixed(1)}`).join(" ");
    return (
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={1.8}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    );
  }

  const gridYs = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90].filter(
    (v) => v >= minHR && v <= maxHR,
  );

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <div className="mb-1 flex items-start justify-between gap-4">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          전략 안정성 — 폴드별 적중률
        </p>
        {has1d && (
          <div className="inline-flex overflow-hidden rounded-full border border-white/10 bg-black/30 p-0.5">
            {(["7d", "1d"] as const).map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => setHorizon(h)}
                className={`cursor-pointer rounded-full px-3 py-1 font-mono text-[0.60rem] uppercase tracking-[0.10em] transition ${
                  horizon === h ? "bg-white/12 text-white" : "text-white/34 hover:text-white/60"
                }`}
                aria-pressed={horizon === h}
              >
                T+{h}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* T+1 vs T+7 comparison banner */}
      {has1d && (
        <div className="mb-4 flex flex-wrap gap-4 rounded-lg border border-white/6 bg-white/[0.02] px-4 py-2.5">
          <span className="font-mono text-[0.62rem] text-white/50">
            <span className="text-[var(--accent-green)]/80">T+7</span> avg core{" "}
            <span className="tabular-nums text-[var(--accent-green)]">{avg7Core !== null ? `${(avg7Core * 100).toFixed(1)}%` : "—"}</span>
            {" "}— 7일 horizon에서 유효한 edge 존재
          </span>
          <span className="font-mono text-[0.62rem] text-white/50">
            <span className="text-[var(--accent-warning)]/80">T+1</span> avg core{" "}
            <span className="tabular-nums text-[var(--accent-warning)]">{avg1Core !== null ? `${(avg1Core * 100).toFixed(1)}%` : "—"}</span>
            {" "}— 랜덤 수준, 단기 예측 불가
          </span>
        </div>
      )}

      <p className="mb-5 font-mono text-[0.68rem] leading-5 text-white/38">
        OOS 폴드별 결과 (엠바고 7일) · Core vs Full PCA
      </p>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full max-w-[560px]"
          aria-label="Walk-forward hit rate by fold"
        >
          {/* grid + y-axis labels */}
          {gridYs.map((hr) => (
            <g key={hr}>
              <line
                x1={PX} y1={py(hr)} x2={W - PX} y2={py(hr)}
                stroke={hr === 0.5 ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.05)"}
                strokeWidth={hr === 0.5 ? 1 : 0.75}
                strokeDasharray={hr === 0.5 ? undefined : "3,3"}
              />
              <text
                x={PX - 5} y={py(hr) + 3.5}
                textAnchor="end"
                style={{ fontSize: 8.5, fill: "rgba(255,255,255,0.24)", fontVariantNumeric: "tabular-nums" }}
              >
                {(hr * 100).toFixed(0)}%
              </text>
            </g>
          ))}

          {/* average lines (dashed) */}
          {avgCore !== null && (
            <line
              x1={PX} y1={py(avgCore)} x2={W - PX} y2={py(avgCore)}
              stroke="rgba(14,203,129,0.28)" strokeWidth={1.2} strokeDasharray="6,4"
            />
          )}
          {avgFull !== null && (
            <line
              x1={PX} y1={py(avgFull)} x2={W - PX} y2={py(avgFull)}
              stroke="rgba(139,92,246,0.28)" strokeWidth={1.2} strokeDasharray="6,4"
            />
          )}

          {/* lines */}
          {polyline(coreFolds, "rgba(14,203,129,0.72)")}
          {polyline(fullFolds, "rgba(139,92,246,0.72)")}

          {/* dots — core */}
          {coreFolds.map((p) => (
            <g key={`c${p.fold}`}>
              <circle cx={px(p.fold)} cy={py(p.hitRate)} r={4} fill="#0ECB81" fillOpacity={0.72} />
              <title>{`Fold ${p.fold} (${p.testStart}) Core: ${pctLabel(p.hitRate)}`}</title>
            </g>
          ))}

          {/* dots — full */}
          {fullFolds.map((p) => (
            <g key={`f${p.fold}`}>
              <circle cx={px(p.fold)} cy={py(p.hitRate)} r={3.5} fill="#8B5CF6" fillOpacity={0.72} />
              <title>{`Fold ${p.fold} (${p.testStart}) Full: ${pctLabel(p.hitRate)}`}</title>
            </g>
          ))}

          {/* x-axis fold labels */}
          {coreFolds.filter((_, i) => i % 2 === 0 || coreFolds.length <= 8).map((p) => (
            <text
              key={`lbl${p.fold}`}
              x={px(p.fold)} y={H - 4}
              textAnchor="middle"
              style={{ fontSize: 7.5, fill: "rgba(255,255,255,0.20)" }}
            >
              {p.testStart.slice(2)}
            </text>
          ))}
        </svg>
      </div>

      {/* legend */}
      <div className="mt-3 flex flex-wrap gap-5">
        <LegendItem color="rgb(14,203,129)" label={`Core  avg ${avgCore !== null ? pctLabel(avgCore) : "—"}`} />
        <LegendItem color="rgb(139,92,246)" label={`Full  avg ${avgFull !== null ? pctLabel(avgFull) : "—"}`} dashed />
        <div className="flex items-center gap-2">
          <div
            className="h-px w-6"
            style={{
              background:
                "repeating-linear-gradient(90deg,rgba(255,255,255,0.28) 0,rgba(255,255,255,0.28) 5px,transparent 5px,transparent 9px)",
            }}
          />
          <span className="font-mono text-[0.60rem] text-white/38">group average</span>
        </div>
      </div>
    </div>
  );
}

function LegendItem({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-0.5 w-6 rounded-full"
        style={{
          background: dashed
            ? `repeating-linear-gradient(90deg,${color} 0,${color} 5px,transparent 5px,transparent 9px)`
            : color,
        }}
      />
      <span className="font-mono text-[0.60rem] text-white/44">{label}</span>
    </div>
  );
}

// ─── Signal Improvement Matrix ───────────────────────────────────────────────
//
// Comparison bars: vol_regime_v2 + incremental filters (2026-05-14 audit).
// Data source: docs/analysis/signal-improvement-audit-20260514.md (hardcoded).

type ScenarioRow = {
  label: string;
  sublabel: string;
  n: number;
  hitRate: number;
  meanRet: number;
  coverage: number;
  isBase?: boolean;
  lowN?: boolean;
};

const IMPROVEMENT_SCENARIOS: ScenarioRow[] = [
  {
    label: "Base",
    sublabel: "vol_regime_v2 + FNG < 70 · coverage ≈14%",
    n: 76, hitRate: 0.711, meanRet: 2.18, coverage: 14.3,
    isBase: true,
  },
  {
    label: "+ Taker ≤ 0.5",
    sublabel: "매도 쏠림 / 중립 구간만 허용",
    n: 48, hitRate: 0.792, meanRet: 2.79, coverage: 9.0,
  },
  {
    label: "+ 직전 7d 하락",
    sublabel: "ret7_lag < 0 (평균 회귀 압력)",
    n: 29, hitRate: 0.862, meanRet: 3.28, coverage: 5.5,
    lowN: true,
  },
  {
    label: "+ 조합 (taker + 하락)",
    sublabel: "두 필터 동시 적용",
    n: 25, hitRate: 0.880, meanRet: 3.26, coverage: 4.7,
    lowN: true,
  },
];

export function SignalImprovementMatrix() {
  const [active, setActive] = useState<number | null>(null);
  const maxHit = Math.max(...IMPROVEMENT_SCENARIOS.map((s) => s.hitRate));
  const base   = IMPROVEMENT_SCENARIOS[0].hitRate;

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <div className="mb-1">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          신호 개선 분석 — 필터 추가 효과
        </p>
      </div>
      <p className="mb-6 font-mono text-[0.68rem] leading-5 text-white/38">
        필터 추가 시 T+7 적중률 변화 · vol_regime_v2 기준 · 539일 분석
      </p>

      {/* Distinction note: this "Base" ≠ BaselineCIChart vol_regime_v2 */}
      <div className="mb-4 rounded-xl border border-[var(--accent-primary)]/12 bg-[var(--accent-primary)]/[0.04] px-4 py-2.5">
        <p className="font-mono text-[0.62rem] leading-5 text-white/52">
          <span className="text-[var(--accent-primary)]/80 font-semibold">주의</span>: 이 표의 &ldquo;Base&rdquo;(hit 71.1%, n=76)는 FNG&lt;70 필터를 추가로 적용한 결과입니다.
          Baseline CI 차트의 vol_regime_v2(hit 60.7%, coverage 56.3%)와 <em>다른 신호</em>입니다.
        </p>
      </div>

      <div className="space-y-3">
        {IMPROVEMENT_SCENARIOS.map((s, idx) => {
          const barW   = (s.hitRate / maxHit) * 100;
          const uplift = idx > 0 ? (s.hitRate - base) * 100 : null;
          const isActive = active === idx;

          return (
            <article
              key={idx}
              className={`cursor-default rounded-2xl border p-4 transition-all duration-150 ${
                isActive
                  ? "border-white/20 bg-white/[0.06]"
                  : s.isBase
                    ? "border-white/12 bg-white/[0.04]"
                    : "border-white/6 bg-white/[0.02] hover:border-white/12 hover:bg-white/[0.04]"
              }`}
              onMouseEnter={() => setActive(idx)}
              onMouseLeave={() => setActive(null)}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                {/* left: labels */}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className={`text-[0.84rem] font-semibold ${s.isBase ? "text-white/88" : "text-white/70"}`}>
                      {s.label}
                    </p>
                    {s.lowN && (
                      <span className="rounded-full border border-[var(--accent-warning)]/30 bg-[var(--accent-warning)]/10 px-2 py-0.5 font-mono text-[0.54rem] text-[var(--accent-warning)]/80">
                        소표본
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 font-mono text-[0.62rem] text-white/34">{s.sublabel}</p>
                  <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-[0.60rem] text-white/30">
                    <span>n = {s.n}</span>
                    <span>coverage {s.coverage.toFixed(1)}%</span>
                    <span>avg ret +{s.meanRet.toFixed(2)}%</span>
                  </div>
                </div>

                {/* right: hit rate */}
                <div className="shrink-0 text-right">
                  <p
                    className={`font-mono text-[1.05rem] font-bold tabular-nums ${
                      s.hitRate >= 0.86
                        ? "text-[var(--accent-green)]"
                        : s.hitRate >= 0.77
                          ? "text-[var(--accent-green)]/80"
                          : "text-white/70"
                    }`}
                  >
                    {(s.hitRate * 100).toFixed(1)}%
                  </p>
                  {uplift !== null && (
                    <p className="font-mono text-[0.60rem] text-[var(--accent-green)]/68">
                      +{uplift.toFixed(1)}pp
                    </p>
                  )}
                </div>
              </div>

              {/* bar */}
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/6">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${barW}%`,
                    background:
                      s.hitRate === maxHit
                        ? "var(--accent-green)"
                        : s.isBase
                          ? "rgba(255,255,255,0.35)"
                          : "rgba(14,203,129,0.55)",
                    boxShadow: s.hitRate === maxHit ? "0 0 10px rgba(14,203,129,0.35)" : "none",
                  }}
                />
              </div>
            </article>
          );
        })}
      </div>

      {/* footnote */}
      <div className="mt-5 rounded-xl border border-[var(--accent-warning)]/16 bg-[var(--accent-warning)]/5 px-4 py-3">
        <p className="font-mono text-[0.62rem] leading-5 text-[var(--accent-warning)]/74">
          <strong>권고</strong>: taker 단독 필터(n=48)가 통계적으로 더 안정적.
          조합 필터(n=25)는 추가 60일 out-of-sample 검증 후 적용 판단.
          miss 원인은 VIX·FNG가 아닌 <em>직전 모멘텀 과열</em>이 핵심.
        </p>
      </div>
    </div>
  );
}

// ─── PCA Interpretation Card ─────────────────────────────────────────────────
//
// One-sentence economic summary of each PCA index.

type PcaInterpEntry = {
  tab: "Full" | "Core";
  explained: string;
  summary: string;
  topFeatures: { label: string; loading: number }[];
};

const PCA_INTERP: PcaInterpEntry[] = [
  {
    tab: "Core",
    explained: "80.2%",
    summary: "F&G + 뉴스감성 + 펀딩레이트의 복합 리스크 선호도 지수. 세 지표 모두 양(+)으로 지수 상승은 탐욕 우세를 의미.",
    topFeatures: [
      { label: "F&G",         loading: +0.628 },
      { label: "뉴스 감성",   loading: +0.593 },
      { label: "펀딩레이트",  loading: +0.503 },
    ],
  },
  {
    tab: "Full",
    explained: "85.0%",
    summary: "LSR 역방향(숏 쏠림 = 반등 신호)과 VIX 역방향을 추가로 반영한 시장 구조 종합 지수. 공포·탐욕 + 시장 미시구조를 하나로 압축.",
    topFeatures: [
      { label: "LSR (역)",      loading: -0.402 },
      { label: "VIX (역)",      loading: -0.311 },
      { label: "F&G",           loading: +0.484 },
      { label: "뉴스 감성",     loading: +0.476 },
      { label: "VIX Regime",    loading: +0.343 },
    ],
  },
];

export function PcaInterpretationCard() {
  const [active, setActive] = useState<"Full" | "Core">("Core");
  const entry = PCA_INTERP.find((e) => e.tab === active) ?? PCA_INTERP[0];
  const maxAbs = Math.max(...entry.topFeatures.map((f) => Math.abs(f.loading)));

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            PC1 경제적 해석
          </p>
          <p className="mt-1 font-mono text-[0.68rem] text-white/38">
            분산 설명력 {entry.explained} · 로딩 절대값 기준
          </p>
        </div>
        <div className="inline-flex overflow-hidden rounded-full border border-white/10 bg-black/30 p-1">
          {(["Core", "Full"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActive(tab)}
              className={`cursor-pointer rounded-full px-4 py-1.5 font-mono text-[0.64rem] uppercase tracking-[0.12em] transition ${
                active === tab ? "bg-white/12 text-white" : "text-white/34 hover:text-white/60"
              }`}
              aria-pressed={active === tab}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* economic summary */}
      <div className="mb-5 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
        <p className="font-mono text-[0.70rem] leading-6 text-white/66">{entry.summary}</p>
      </div>

      {/* loading bars */}
      <div className="space-y-2.5">
        {entry.topFeatures.map((f) => {
          const pos    = f.loading >= 0;
          const pct    = (Math.abs(f.loading) / maxAbs) * 44; // max 44% half-bar
          return (
            <div key={f.label} className="flex items-center gap-3">
              <div className="w-[72px] text-right font-mono text-[0.62rem] text-white/44">{f.label}</div>
              <div className="relative flex h-6 flex-1 items-center">
                {/* center line */}
                <div className="absolute left-1/2 h-full w-px -translate-x-1/2 bg-white/12" />
                {/* bar */}
                <div
                  className={`absolute h-3 rounded-full ${pos ? "bg-[var(--accent-green)]/64" : "bg-[var(--accent-down)]/56"}`}
                  style={{
                    width: `${pct}%`,
                    [pos ? "left" : "right"]: "50%",
                  }}
                />
              </div>
              <span
                className={`w-[44px] font-mono text-[0.62rem] tabular-nums ${pos ? "text-[var(--accent-green)]/80" : "text-[var(--accent-down)]/80"}`}
              >
                {pos ? "+" : ""}{f.loading.toFixed(3)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-center gap-8 font-mono text-[0.56rem] text-white/18">
        <span className="text-[var(--accent-down)]/50">← 지수 하락</span>
        <span className="text-[var(--accent-green)]/50">지수 상승 →</span>
      </div>
    </div>
  );
}

// ─── shared empty state ──────────────────────────────────────────────────────

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex min-h-[140px] items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.015]">
      <p className="font-mono text-[0.68rem] text-white/28">{label}</p>
    </div>
  );
}
