"use client";

import React, { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { AlphaSection, GrangerSection, JsonObject, SentimentInsightArtifact } from "@schema/analysis.types";
import { formatFeatureLabel } from "@/lib/analysis-derive";
import { GrangerSymmetric } from "./GrangerSymmetric";
import { PcaTabs } from "./PcaTabs";
import {
  AlphaValidationBoard,
  AnalysisOverviewDeck,
  DataQualityMatrix,
  RawMetadataExplorer,
  StationarityPanel,
  TargetDiagnosticsPanel,
} from "./AnalysisDashboardPanels";
import {
  BaselineCIChart,
  GrangerHeatmap,
  InlineExplain,
  PcaInterpretationCard,
  SignalImprovementMatrix,
  WalkForwardTimeseries,
} from "./DataMiningInsights";

// ─── types ───────────────────────────────────────────────────────────────────

type TabId = "summary" | "signal" | "causality" | "factor" | "pipeline" | "guide";

const TABS: { id: TabId; label: string; hint: string }[] = [
  { id: "summary",   label: "Summary",    hint: "핵심 KPI" },
  { id: "signal",    label: "Signal",     hint: "성과 검증" },
  { id: "causality", label: "Causality",  hint: "인과 분석" },
  { id: "factor",    label: "Factor",     hint: "PCA 팩터" },
  { id: "pipeline",  label: "Pipeline",   hint: "전처리·품질" },
  { id: "guide",     label: "Guide",      hint: "읽는 법·용어" },
];

// ─── helpers ──────────────────────────────────────────────────────────────────

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function fmtPct(v: number | null, d = 1): string {
  return v === null ? "—" : `${(v * 100).toFixed(d)}%`;
}

function fmtP(v: number | null): string {
  if (v === null) return "—";
  return v < 0.001 ? "<0.001" : v.toFixed(3);
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asObj(v: unknown): Record<string, unknown> | null {
  if (typeof v === "object" && v !== null && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

// ─── data derivation ─────────────────────────────────────────────────────────

type Kpi = {
  hitRate: number | null;
  sharpe: number | null;
  uplift: number | null;
  forwardCount: number;
  reverseCount: number;
  bestForwardP: number | null;
  bestReverseP: number | null;
  bestForwardLag: number | null;
  bestReverseLag: number | null;
  totalSig: number;
  // promotionGate
  overlayDecision: string | null;
  overlayHitRate: number | null;
  overlayPMedian: number | null;
  overlayRecords: number | null;
  overlayAllOk: boolean;
  // gateStats
  gateTotal: number | null;
  gatePromote: number | null;
  gateStrictPromote: number | null;
};

const SENTIMENT_PREDICTORS = new Set([
  "news_sentiment_mean",
  "sentiment_momentum",
  "fng_value",
  "fng_change_1d",
]);

function deriveKpi(artifact: SentimentInsightArtifact): Kpi {
  const bm7 = artifact.alpha?.baselineMetrics?.["7"];
  const isObj = typeof bm7 === "object" && bm7 !== null && !Array.isArray(bm7);
  const vr2 = isObj ? ((bm7 as JsonObject)["vol_regime_v2"] as JsonObject | undefined) : undefined;
  const au  = isObj ? ((bm7 as JsonObject)["always_up"]      as JsonObject | undefined) : undefined;

  const hitRate = num(vr2?.hit_rate);
  const sharpe  = num(vr2?.sharpe);
  const auHit   = num(au?.hit_rate);

  const sigOpt = artifact.granger.results.filter((r) => r.significant && r.optimalLag);

  const forward = sigOpt
    .filter((r) => SENTIMENT_PREDICTORS.has(r.predictor) && r.target === "btc_log_return")
    .sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1));

  const reverse = sigOpt
    .filter(
      (r) =>
        r.predictor === "btc_log_return" &&
        (SENTIMENT_PREDICTORS.has(r.target) || r.target.includes("sentiment")),
    )
    .sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1));

  const pgOverlay = asObj(artifact.alpha?.promotionGate?.["volRegimeV2Overlay"]);
  const gsRaw = artifact.alpha?.gateStats;

  return {
    hitRate,
    sharpe,
    uplift: hitRate !== null && auHit !== null ? hitRate - auHit : null,
    forwardCount: forward.length,
    reverseCount: reverse.length,
    bestForwardP:   forward[0]?.pvalueAdjusted ?? null,
    bestReverseP:   reverse[0]?.pvalueAdjusted ?? null,
    bestForwardLag: forward[0]?.lag ?? null,
    bestReverseLag: reverse[0]?.lag ?? null,
    totalSig:       sigOpt.length,
    overlayDecision: typeof pgOverlay?.["decision"] === "string" ? pgOverlay["decision"] : null,
    overlayHitRate:  num(pgOverlay?.["rollingHitRate"]),
    overlayPMedian:  num(pgOverlay?.["rollingPMedian"]),
    overlayRecords:  num(pgOverlay?.["nRecords"]),
    overlayAllOk:    pgOverlay?.["hitRateOk"] === true && pgOverlay?.["pValueOk"] === true,
    gateTotal:          num(gsRaw?.["totalPredictors"]),
    gatePromote:        num(gsRaw?.["decisionPromoteCount"]),
    gateStrictPromote:  num(gsRaw?.["decisionStrictPromoteCount"]),
  };
}

const BASELINE_LABELS: Record<string, string> = {
  vol_regime_v2:  "Vol Regime v2",
  vol_regime:     "Vol Regime",
  always_up:      "Always Long",
  btc_momo_20d:   "BTC Momo 20d",
  fng_contrarian: "F&G Contrarian",
};

type ScatterPoint = { name: string; label: string; x: number; y: number; z: number; isBest: boolean };

function deriveScatter(artifact: SentimentInsightArtifact): ScatterPoint[] {
  const bm7 = artifact.alpha?.baselineMetrics?.["7"];
  if (typeof bm7 !== "object" || bm7 === null || Array.isArray(bm7)) return [];
  return Object.entries(bm7 as JsonObject).map(([name, data]) => {
    const d = data as JsonObject;
    const cov = num(d.coverage) ?? 0.1;
    return {
      name,
      label: BASELINE_LABELS[name] ?? name,
      x: num(d.hit_rate) ?? 0,
      y: num(d.sharpe) ?? 0,
      z: cov > 1 ? cov / 100 : cov,
      isBest: name === "vol_regime_v2",
    };
  });
}

type LoadingBar = { feature: string; loading: number; color: string };

function deriveLoadings(artifact: SentimentInsightArtifact, mode: "core" | "full"): LoadingBar[] {
  return Object.entries(artifact.pca[mode].loadings)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 8)
    .map(([feature, loading]) => ({
      feature: formatFeatureLabel(feature).slice(0, 18),
      loading,
      color: loading >= 0 ? "#0ECB81" : "#F6465D",
    }));
}

// ─── shared primitives ────────────────────────────────────────────────────────

const DARK_TICK = { fill: "rgba(255,255,255,0.28)", fontSize: 10 };

function KpiCard({
  label,
  sub,
  value,
  green = false,
}: {
  label: string;
  sub?: string;
  value: string;
  green?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border p-5 ${
        green
          ? "border-[var(--accent-green)]/20 bg-[var(--accent-green)]/[0.04]"
          : "border-white/8 bg-white/[0.02]"
      }`}
    >
      <p className="font-mono text-[0.58rem] uppercase tracking-[0.14em] text-white/36">{label}</p>
      {sub && <p className="mt-0.5 font-mono text-[0.54rem] text-white/20">{sub}</p>}
      <p
        className={`mt-3 font-mono text-[1.5rem] font-bold tabular-nums leading-none ${
          green ? "text-[var(--accent-green)]" : "text-white/80"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

// ─── Signal Space scatter ─────────────────────────────────────────────────────

function SignalSpaceChart({ data }: { data: ScatterPoint[] }) {
  if (data.length === 0) return null;

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <p className="mb-1 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
        신호 성과 공간
      </p>
      <p className="mb-5 font-mono text-[0.68rem] text-white/38">
        버블 크기 = coverage · 우상단 = 고품질
      </p>
      <InlineExplain>
        <p>5가지 전략을 적중률(X축)과 Sharpe 비율(Y축) 기준으로 배치합니다.</p>
        <p>버블이 크고 우상단에 있을수록 좋은 전략입니다. 초록 버블이 현재 메인 신호(vol_regime_v2)입니다.</p>
        <p>50% 점선 왼쪽에 있으면 랜덤 수준 이하입니다.</p>
      </InlineExplain>
      <ResponsiveContainer width="100%" height={240}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <XAxis
            dataKey="x"
            type="number"
            name="Hit Rate"
            domain={[0.45, 0.72]}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={DARK_TICK}
            label={{
              value: "Hit Rate (T+7)",
              position: "insideBottom",
              offset: -14,
              fill: "rgba(255,255,255,0.22)",
              fontSize: 10,
            }}
          />
          <YAxis
            dataKey="y"
            type="number"
            name="Sharpe"
            domain={[0, 7]}
            tick={DARK_TICK}
            label={{
              value: "Sharpe",
              angle: -90,
              position: "insideLeft",
              fill: "rgba(255,255,255,0.22)",
              fontSize: 10,
            }}
          />
          <ZAxis dataKey="z" range={[60, 500]} />
          <ReferenceLine x={0.5} stroke="rgba(255,255,255,0.10)" strokeDasharray="4 4" />
          <RechartsTooltip
            cursor={false}
            content={(props) => {
              const payload = props.payload as unknown as { payload: ScatterPoint }[] | undefined;
              if (!payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="rounded-lg border border-white/14 bg-black/90 px-3 py-2 shadow-xl">
                  <p
                    className={`font-mono text-[0.72rem] font-semibold ${
                      d.isBest ? "text-[var(--accent-green)]" : "text-white/80"
                    }`}
                  >
                    {d.label}
                  </p>
                  <p className="mt-0.5 font-mono text-[0.60rem] text-white/44">
                    Hit {(d.x * 100).toFixed(1)}% · Sharpe {d.y.toFixed(2)} · Cov{" "}
                    {(d.z * 100).toFixed(1)}%
                  </p>
                </div>
              );
            }}
          />
          <Scatter data={data}>
            {data.map((entry, i) => (
              <Cell
                key={`cell-${i}`}
                fill={entry.isBest ? "rgba(14,203,129,0.65)" : "rgba(255,255,255,0.20)"}
                stroke={entry.isBest ? "#0ECB81" : "rgba(255,255,255,0.35)"}
                strokeWidth={1.5}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Causality direction card ──────────────────────────────────────────────────

function CausalityDirectionCard({ kpi, granger }: { kpi: Kpi; granger: GrangerSection }) {
  const [showOther, setShowOther] = useState(false);

  const sigOpt = useMemo(
    () => granger.results.filter((r) => r.significant && r.optimalLag),
    [granger],
  );

  const catSentToPrice = useMemo(
    () =>
      sigOpt
        .filter((r) => SENTIMENT_PREDICTORS.has(r.predictor) && r.target === "btc_log_return")
        .sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1)),
    [sigOpt],
  );

  const catPriceToSent = useMemo(
    () =>
      sigOpt
        .filter(
          (r) =>
            r.predictor === "btc_log_return" &&
            (SENTIMENT_PREDICTORS.has(r.target) || r.target.includes("sentiment")),
        )
        .sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1)),
    [sigOpt],
  );

  const catOther = useMemo(() => {
    const sentSet = new Set(catSentToPrice);
    const revSet = new Set(catPriceToSent);
    return sigOpt
      .filter((r) => !sentSet.has(r) && !revSet.has(r))
      .sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1));
  }, [sigOpt, catSentToPrice, catPriceToSent]);

  function PairRow({ r }: { r: (typeof sigOpt)[0] }) {
    const pred = r.predictor.replace(/_lag\d+$/, "").replace(/_zscore_\d+d$/, "");
    const tgt  = r.target.replace(/_lag\d+$/, "").replace(/_zscore_\d+d$/, "");
    return (
      <div className="flex items-center gap-2 py-1">
        <span className="flex-1 truncate font-mono text-[0.60rem] text-white/52">
          {pred} → {tgt}
        </span>
        <span className="shrink-0 font-mono text-[0.58rem] text-white/28">lag={r.lag}</span>
        <span className="shrink-0 w-[48px] text-right font-mono text-[0.60rem] tabular-nums text-[var(--accent-green)]/76">
          {r.pvalueAdjusted !== null && r.pvalueAdjusted < 0.001 ? "<0.001" : r.pvalueAdjusted?.toFixed(3) ?? "—"}
        </span>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <p className="mb-1 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
        인과 방향 요약
      </p>
      <p className="mb-5 font-mono text-[0.68rem] text-white/38">
        {sigOpt.length}개 유의 쌍 · FDR-BH 보정 · {granger.correction.nTests}개 검정
      </p>
      <InlineExplain>
        <p>감성 데이터와 BTC 가격 사이에 어떤 방향의 인과관계가 있는지 정리한 카드입니다.</p>
        <p>'감성→가격' 쌍이 있다는 것은 오늘의 감성 데이터가 며칠 후 가격 변동을 예측하는 데 도움이 된다는 의미입니다.</p>
        <p>'가격→감성' 역방향도 자연스러운 현상입니다 — 가격이 오르면 사람들 감성도 좋아지기 때문입니다.</p>
      </InlineExplain>

      <div className="space-y-3">
        {/* Category 1: Sentiment → Price */}
        <div
          className={`rounded-xl border p-4 ${
            catSentToPrice.length > 0
              ? "border-[var(--accent-green)]/20 bg-[var(--accent-green)]/[0.04]"
              : "border-white/8 bg-white/[0.02]"
          }`}
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="font-mono text-[0.72rem] font-semibold text-white/80">Sentiment → Price</p>
            <span
              className={`font-mono text-[0.80rem] font-bold tabular-nums ${
                catSentToPrice.length > 0 ? "text-[var(--accent-green)]" : "text-white/30"
              }`}
            >
              {catSentToPrice.length} pairs
            </span>
          </div>
          <p className="mb-2 font-mono text-[0.58rem] text-white/32">예측 방향 · lag {kpi.bestForwardLag ?? "?"}</p>
          {catSentToPrice.map((r, i) => <PairRow key={i} r={r} />)}
          {catSentToPrice.length === 0 && (
            <p className="font-mono text-[0.60rem] text-white/24">없음</p>
          )}
        </div>

        {/* Category 2: Price → Sentiment */}
        <div className="rounded-xl border border-[var(--accent-warning)]/15 bg-[var(--accent-warning)]/[0.03] p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="font-mono text-[0.72rem] font-semibold text-white/80">Price → Sentiment</p>
            <span className="font-mono text-[0.80rem] font-bold tabular-nums text-[var(--accent-warning)]">
              {catPriceToSent.length} pairs
            </span>
          </div>
          <p className="mb-2 font-mono text-[0.58rem] text-white/32">역방향 · lag {kpi.bestReverseLag ?? "?"}</p>
          {catPriceToSent.map((r, i) => <PairRow key={i} r={r} />)}
          {catPriceToSent.length === 0 && (
            <p className="font-mono text-[0.60rem] text-white/24">없음</p>
          )}
        </div>

        {/* Category 3: Other cross-series */}
        {catOther.length > 0 && (
          <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
            <button
              type="button"
              onClick={() => setShowOther((v) => !v)}
              className="flex w-full cursor-pointer items-center justify-between gap-3"
            >
              <div className="flex items-center gap-3">
                <p className="font-mono text-[0.72rem] font-semibold text-white/60">기타 교차 지표</p>
                <span className="font-mono text-[0.58rem] text-white/28">가격·감성 ↔ 파생 지표</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[0.80rem] font-bold tabular-nums text-white/46">
                  {catOther.length} pairs
                </span>
                <span className="font-mono text-[0.64rem] text-white/28">{showOther ? "▲" : "▼"}</span>
              </div>
            </button>
            {showOther && (
              <div className="mt-3 border-t border-white/6 pt-3">
                {catOther.map((r, i) => <PairRow key={i} r={r} />)}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="mt-4 rounded-xl border border-white/6 bg-white/[0.02] px-4 py-3">
        <p className="font-mono text-[0.63rem] leading-5 text-white/56">
          <span className="font-semibold text-white/80">결론:</span> 양방향 관계 모두 확인. 역방향(가격→감성)이
          더 강하나, 순방향 신호도 유의미 — vol_regime 필터와 조합 시 활용 가능.
        </p>
      </div>
    </div>
  );
}

// ─── PCA loading chart ────────────────────────────────────────────────────────

function PcaLoadingChart({ artifact }: { artifact: SentimentInsightArtifact }) {
  const [mode, setMode] = useState<"core" | "full">("core");
  const data = useMemo(() => deriveLoadings(artifact, mode), [artifact, mode]);
  const ev = mode === "core" ? artifact.pca.core.explainedVariance : artifact.pca.full.explainedVariance;

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            PC1 팩터 로딩
          </p>
          <p className="mt-1 font-mono text-[0.68rem] text-white/38">
            분산 설명력 {ev !== undefined ? `${(ev * 100).toFixed(1)}%` : "—"} · 절대값 내림차순
          </p>
        </div>
        <div className="inline-flex overflow-hidden rounded-full border border-white/10 bg-black/30 p-0.5">
          {(["core", "full"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`cursor-pointer rounded-full px-4 py-1.5 font-mono text-[0.62rem] uppercase tracking-[0.10em] transition ${
                mode === m ? "bg-white/12 text-white" : "text-white/34 hover:text-white/60"
              }`}
              aria-pressed={mode === m}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <InlineExplain>
        <p>여러 지표가 PC1(복합 지수)에 얼마나 기여하는지 보여주는 차트입니다.</p>
        <p>초록 막대(양+)는 지수가 오를수록 함께 오르는 지표, 빨강 막대(음-)는 반대 방향으로 움직이는 지표입니다.</p>
        <p>막대가 길수록 해당 지표가 지수에 더 큰 영향을 미칩니다.</p>
      </InlineExplain>

      <ResponsiveContainer width="100%" height={260}>
        <BarChart layout="vertical" data={data} margin={{ top: 0, right: 30, bottom: 0, left: 10 }}>
          <XAxis
            type="number"
            domain={[-1, 1]}
            tick={DARK_TICK}
            tickFormatter={(v: number) => v.toFixed(1)}
          />
          <YAxis
            type="category"
            dataKey="feature"
            width={104}
            tick={{ fill: "rgba(255,255,255,0.44)", fontSize: 9.5 }}
          />
          <ReferenceLine x={0} stroke="rgba(255,255,255,0.18)" />
          <RechartsTooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={(props) => {
              const payload = props.payload as unknown as { payload: LoadingBar }[] | undefined;
              if (!payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="rounded-lg border border-white/14 bg-black/90 px-3 py-2 shadow-xl">
                  <p className="font-mono text-[0.68rem] text-white/80">{d.feature}</p>
                  <p
                    className={`font-mono text-[0.80rem] font-bold tabular-nums ${
                      d.loading >= 0 ? "text-[var(--accent-green)]" : "text-[var(--accent-down)]"
                    }`}
                  >
                    {d.loading >= 0 ? "+" : ""}
                    {d.loading.toFixed(3)}
                  </p>
                </div>
              );
            }}
          />
          <Bar dataKey="loading" radius={[0, 3, 3, 0]}>
            {data.map((entry, i) => (
              <Cell key={`cell-${i}`} fill={entry.color} fillOpacity={0.72} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-3 flex justify-center gap-8 font-mono text-[0.58rem] text-white/22">
        <span className="text-[var(--accent-down)]/70">← 지수 하락 방향</span>
        <span className="text-[var(--accent-green)]/70">지수 상승 방향 →</span>
      </div>
    </div>
  );
}

// ─── Backtest table ───────────────────────────────────────────────────────────

type BacktestRow = {
  predictor: string;
  displayName: string;
  cumRet: number | null;
  bnhCumRet: number | null;
  sharpe: number | null;
  sharpeLo: number | null;
  sharpeHi: number | null;
  drawdown: number | null;
  nTrades: number | null;
  txCost: number | null;
  grangerSig: boolean;
};

function parseBacktest(alpha?: AlphaSection): BacktestRow[] {
  const raw = alpha?.backtest;
  if (!Array.isArray(raw)) return [];
  return (raw as JsonObject[])
    .map((b) => {
      const pred = str(b["predictor"]);
      const clean = pred.replace(/_lag\d+$/, "").replace(/_inverted$/, "");
      return {
        predictor: pred,
        displayName: formatFeatureLabel(clean).slice(0, 26),
        cumRet:    num(b["strategy_cumulative_return"]),
        bnhCumRet: num(b["bnh_cumulative_return"]),
        sharpe:    num(b["sharpe_ratio"]),
        sharpeLo:  num(b["sharpe_ci_lower"]),
        sharpeHi:  num(b["sharpe_ci_upper"]),
        drawdown:  num(b["max_drawdown"]),
        nTrades:   typeof b["n_trades"] === "number" ? b["n_trades"] : null,
        txCost:    num(b["transaction_cost_bps"]),
        grangerSig: b["granger_significant"] === true,
      };
    })
    .sort((a, b) => (b.cumRet ?? -999) - (a.cumRet ?? -999));
}

function BacktestTable({ alpha }: { alpha?: AlphaSection }) {
  const rows = useMemo(() => parseBacktest(alpha), [alpha]);
  if (rows.length === 0) return null;

  const txCost = rows[0]?.txCost;

  return (
    <div className="rounded-2xl border border-white/10 bg-black/24 p-6">
      <p className="mb-1 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
        예측변수별 백테스트 — T+7
      </p>
      <p className="mb-5 font-mono text-[0.68rem] text-white/38">
        {rows.length}개 예측변수 · 거래비용 {txCost ?? 10}bps/leg · 누적수익 내림차순
      </p>
      <InlineExplain>
        <p>각 지표를 단독으로 사용했을 때의 과거 성과표입니다.</p>
        <p>거래비용(수수료)을 반영한 현실적인 누적수익과 최대낙폭(MDD)을 함께 보여줍니다.</p>
        <p>초록 점(•)이 있는 행은 Granger 검정을 통과한 지표 — 단순 상관관계가 아닌 예측 선행성이 검증된 것입니다.</p>
      </InlineExplain>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-left">
          <thead>
            <tr className="border-b border-white/6">
              {[
                { label: "Predictor",         w: "w-[200px]" },
                { label: "Cum Ret",            w: "w-[72px]" },
                { label: "Buy&Hold",           w: "w-[72px]" },
                { label: "Sharpe (95% CI)",    w: "w-[160px]" },
                { label: "Max DD",             w: "w-[72px]" },
                { label: "Trades",             w: "w-[52px]" },
              ].map(({ label, w }) => (
                <th
                  key={label}
                  className={`${w} pb-2 pr-4 font-mono text-[0.56rem] uppercase tracking-[0.10em] text-white/24`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.03]">
            {rows.map((b, i) => (
              <tr key={i} className="group hover:bg-white/[0.02]">
                <td className="py-2 pr-4 font-mono text-[0.63rem] text-white/58">
                  {b.displayName}
                  {b.grangerSig && (
                    <span className="ml-1.5 inline-block h-1.5 w-1.5 translate-y-[-1px] rounded-full bg-[var(--accent-green)]/55 align-middle" title="Granger 유의" />
                  )}
                </td>
                <td
                  className={`py-2 pr-4 font-mono text-[0.65rem] font-semibold tabular-nums ${
                    (b.cumRet ?? 0) >= 0 ? "text-[var(--accent-green)]" : "text-[var(--accent-down)]"
                  }`}
                >
                  {b.cumRet !== null
                    ? `${b.cumRet >= 0 ? "+" : ""}${(b.cumRet * 100).toFixed(1)}%`
                    : "—"}
                </td>
                <td className="py-2 pr-4 font-mono text-[0.63rem] tabular-nums text-white/30">
                  {b.bnhCumRet !== null ? `${(b.bnhCumRet * 100).toFixed(1)}%` : "—"}
                </td>
                <td className="py-2 pr-4 font-mono text-[0.63rem] tabular-nums">
                  <span
                    className={
                      (b.sharpe ?? 0) >= 0 ? "text-white/56" : "text-[var(--accent-down)]/70"
                    }
                  >
                    {b.sharpe !== null ? b.sharpe.toFixed(2) : "—"}
                  </span>
                  {b.sharpeLo !== null && b.sharpeHi !== null && (
                    <span className="text-[0.56rem] text-white/20">
                      {" "}[{b.sharpeLo.toFixed(1)}, {b.sharpeHi.toFixed(1)}]
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4 font-mono text-[0.63rem] tabular-nums text-[var(--accent-down)]/60">
                  {b.drawdown !== null ? `${(b.drawdown * 100).toFixed(1)}%` : "—"}
                </td>
                <td className="py-2 font-mono text-[0.63rem] tabular-nums text-white/30">
                  {b.nTrades ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-mono text-[0.58rem] text-white/20">Sharpe CI: 블록 부트스트랩 B=1000 · 왕복 {(txCost ?? 10) * 2}bps</span>
        <span className="flex items-center gap-1.5 font-mono text-[0.58rem] text-white/20">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent-green)]/55" /> Granger 유의
        </span>
      </div>
    </div>
  );
}

// ─── Guide tab data ──────────────────────────────────────────────────────────

type GlossaryEntry = {
  term: string;
  en?: string;
  definition: string;
  cat: "성과" | "통계" | "방법론" | "신호";
};

const GLOSSARY: GlossaryEntry[] = [
  { term: "적중률", en: "Hit Rate", cat: "성과", definition: "신호가 발화한 날로부터 7일 후 BTC 가격이 상승한 비율. 50%가 랜덤(동전 던지기) 기준선이며, 높을수록 예측력이 좋습니다." },
  { term: "Sharpe Ratio", cat: "성과", definition: "수익률을 변동성(위험)으로 나눈 지표. 1.0 이상이면 우수, 0 이하면 불안정. 거래비용까지 반영한 현실적 지표입니다." },
  { term: "커버리지", en: "Coverage", cat: "성과", definition: "전체 기간 중 신호가 발화한 날의 비율. 높으면 더 자주 사용 가능하지만 조건이 느슨하다는 의미이기도 합니다." },
  { term: "최대낙폭", en: "MDD", cat: "성과", definition: "전략이 최고점에서 최저점까지 하락한 최대 폭. -20%면 고점 대비 20% 손실을 경험했다는 뜻입니다." },
  { term: "누적수익", en: "Cumulative Return", cat: "성과", definition: "전략 기간 전체의 총 수익률. Buy & Hold(그냥 보유)와 비교해 전략의 실질 가치를 평가합니다." },
  { term: "p-value", cat: "통계", definition: "우연히 이런 결과가 나올 확률. 0.05(5%) 이하면 통계적으로 유의하다고 봅니다. 숫자가 낮을수록 결과가 우연이 아닌 실제 패턴일 가능성이 높습니다." },
  { term: "신뢰구간", en: "Confidence Interval", cat: "통계", definition: "'95% CI [40%, 70%]'는 진짜 값이 40~70% 사이에 있을 확률이 95%라는 의미입니다. 범위가 좁을수록 추정이 정밀합니다." },
  { term: "Bootstrap CI", cat: "통계", definition: "실제 데이터를 수천 번 반복 샘플링해 신뢰구간을 추정하는 방법. 데이터가 적을 때 특히 유용합니다." },
  { term: "FDR-BH 보정", cat: "통계", definition: "검정을 여러 번 반복하면 우연히 유의한 결과가 나올 확률이 높아집니다. FDR-BH는 이 다중 검정 함정을 보정하는 통계 기법입니다." },
  { term: "Granger 인과검정", en: "Granger Causality", cat: "방법론", definition: "A의 과거 값이 B를 예측하는 데 통계적으로 도움이 되는지 검증합니다. 일반적인 원인과 달리 예측 선행성(temporal precedence)을 측정합니다." },
  { term: "PCA", en: "주성분분석", cat: "방법론", definition: "여러 개의 지표를 하나의 복합 지수(PC1)로 압축하는 방법. 중복 정보를 제거하고 핵심 변동 패턴만 추출합니다." },
  { term: "Walk-Forward 검증", cat: "방법론", definition: "전략을 시간 순서대로 나눠 미래 데이터를 절대 사용하지 않고 검증하는 방법. 과거 데이터에 과적합된 전략을 걸러냅니다." },
  { term: "OOS", en: "Out-of-Sample", cat: "방법론", definition: "전략 개발에 사용하지 않은 기간의 데이터로 검증한 결과. OOS 성과가 좋아야 실전에서도 통할 가능성이 높습니다." },
  { term: "vol_regime_v2", cat: "신호", definition: "이 시스템의 메인 매매 신호. VIX(시장 공포 지수)와 BTC 실현변동성이 모두 낮은 조용한 구간을 포착합니다. 저변동성 구간에서 반등 가능성이 높다는 전제에 기반합니다." },
  { term: "Overlay Gate", cat: "신호", definition: "신호를 실제 운용에 투입하기 전 실시간 품질 모니터링 시스템. 누적 결과가 적중률·p-value 기준을 통과해야 'promote' 판정을 받습니다." },
  { term: "F&G Index", cat: "신호", definition: "암호화폐 시장의 탐욕·공포를 0~100으로 표현한 지수. 0=극단적 공포, 100=극단적 탐욕. 역발상 신호로 활용됩니다." },
  { term: "Taker Imbalance", cat: "신호", definition: "시장가 매수·매도 체결의 불균형. 음수이거나 중립이면 스마트머니가 조용히 축적 중인 신호로 해석합니다." },
];

const CAT_COLORS: Record<string, string> = {
  "성과":   "text-[var(--accent-green)]/70 border-[var(--accent-green)]/20 bg-[var(--accent-green)]/[0.04]",
  "통계":   "text-[var(--accent-primary)]/70 border-[var(--accent-primary)]/20 bg-[var(--accent-primary)]/[0.04]",
  "방법론": "text-[var(--accent-warning)]/70 border-[var(--accent-warning)]/20 bg-[var(--accent-warning)]/[0.04]",
  "신호":   "text-white/52 border-white/12 bg-white/[0.02]",
};

type TabGuide = {
  id: string;
  title: string;
  summary: string;
  steps: string[];
  qa: { q: string; a: string }[];
};

const TAB_GUIDES: TabGuide[] = [
  {
    id: "summary",
    title: "Summary — 핵심 KPI",
    summary: "전략 성과의 핵심 숫자 5개와 전략 간 비교 차트. 처음 이 페이지를 열면 여기부터 보세요.",
    steps: [
      "KPI 5개 카드 — 적중률·Sharpe·인과 p값·Overlay Gate 확인",
      "신호 성과 공간 — 버블이 우상단일수록 좋은 전략",
      "인과 방향 요약 — '감성→가격' 쌍이 있으면 신호에 통계적 근거 존재",
      "결론 배너 — 모든 결과의 한 줄 요약",
    ],
    qa: [
      { q: "Hit Rate 60.7%가 좋은 건가요?", a: "50%가 랜덤(동전 던지기) 기준입니다. 60.7%는 약 10.7%p의 예측 엣지(edge)가 있다는 의미로, 통계적으로 유의미하게 좋은 수치입니다." },
      { q: "Overlay Gate 'promote'는 무슨 뜻인가요?", a: "22일 누적 데이터에서 적중률과 p-value가 운용 투입 기준을 통과했다는 뜻입니다. 아직 실제 투자에 적용되지는 않았고, 60일 이상 누적 후 최종 판단합니다." },
    ],
  },
  {
    id: "signal",
    title: "Signal — 성과 검증",
    summary: "전략 성과를 통계적으로 검증합니다. Bootstrap CI로 신뢰구간을 비교하고, Walk-Forward로 시간적 일관성을 확인합니다.",
    steps: [
      "기본 전략 비교 — 5개 전략의 적중률과 신뢰구간을 나란히 비교",
      "폴드별 적중률 — 시간에 따른 일관성 확인 (들쭉날쭉하면 국면 의존성 있음)",
      "신호 개선 분석 — 필터를 추가할수록 적중률이 어떻게 변하는지 확인",
    ],
    qa: [
      { q: "신뢰구간이 겹치면 어떤 의미인가요?", a: "두 전략의 신뢰구간이 겹치면 성과 차이가 통계적으로 유의하지 않을 수 있습니다. 겹치지 않아야 확실한 우위입니다." },
      { q: "Walk-Forward 점들이 들쭉날쭉한 게 나쁜 건가요?", a: "일부 변동은 정상입니다. 특정 기간에만 급등하고 나머지는 50% 이하라면 시장 국면 의존성이 높다는 경고 신호입니다." },
    ],
  },
  {
    id: "causality",
    title: "Causality — 인과 분석",
    summary: "뉴스 감성이 정말 BTC 가격을 예측하는지 통계적으로 검증합니다. Granger 인과검정으로 시간적 선행성을 측정합니다.",
    steps: [
      "인과관계 매트릭스 — 초록 셀일수록 강한 예측력 (행 → 열 방향)",
      "인과 방향 요약 — 감성→가격(순방향)과 가격→감성(역방향) 쌍 분류",
      "하단 상세 테이블 — 각 쌍의 lag, p-value 원본 수치 확인",
    ],
    qa: [
      { q: "Granger 검정이 통과했다고 실제 인과관계가 있나요?", a: "Granger는 예측 선행성을 검증합니다. 실제 인과관계의 근거이지만, 제3의 변수가 둘 다 움직일 수도 있으니 여러 근거 중 하나로 활용합니다." },
      { q: "역방향(가격→감성)이 더 강한 게 문제인가요?", a: "가격이 감성에 영향을 주는 건 자연스러운 현상입니다. 순방향(감성→가격)도 통계적으로 유의하다는 점이 중요합니다 — 두 방향 모두 확인된 게 신호 근거를 지지합니다." },
    ],
  },
  {
    id: "factor",
    title: "Factor — PCA 팩터",
    summary: "여러 지표를 하나의 복합 지수로 압축한 결과. 어떤 지표가 지수를 주도하는지, 그 경제적 의미를 확인합니다.",
    steps: [
      "PC1 팩터 로딩 — 초록(양)은 지수와 같은 방향, 빨강(음)은 반대 방향",
      "Core/Full 전환 — Core(4개 피처)가 더 안정적, Full(8개)은 더 많은 정보 포함",
      "경제적 해석 카드 — 지수의 의미를 한 문장으로 요약",
    ],
    qa: [
      { q: "Core vs Full 중 어느 게 더 좋은 건가요?", a: "Core(4개 피처)는 과적합 위험이 낮고 해석이 쉽습니다. Full(8개)은 더 많은 정보를 담지만 노이즈가 늘어날 수 있습니다. 일반적으로 Core가 더 안정적입니다." },
      { q: "로딩(loading)이 음수면 나쁜 지표인가요?", a: "아닙니다. 음수 로딩은 그 지표가 지수와 반대 방향으로 움직인다는 뜻입니다. 예를 들어 VIX가 높으면 지수가 낮아지는 것처럼, 이 역방향 관계 자체가 유용한 정보입니다." },
    ],
  },
  {
    id: "pipeline",
    title: "Pipeline — 데이터 품질",
    summary: "원데이터가 어떻게 처리되었는지 확인합니다. 이상치 필터링, 결측치 처리, 각 예측변수의 백테스트 원본 수치를 볼 수 있습니다.",
    steps: [
      "개요 덱 — 총 행 수, 이상치 필터링 비율, 유의 Granger 쌍 수 확인",
      "데이터 품질 — 결측치(ffill) 비율과 소스별 현황 확인",
      "백테스트 표 — 개별 예측변수의 누적수익·Sharpe·최대낙폭 원본 수치",
    ],
    qa: [
      { q: "이상치 필터링이 많으면 문제인가요?", a: "전체의 5% 이하라면 정상입니다. 그 이상이면 데이터 수집 품질 문제나 시장 극단 이벤트가 많았다는 신호입니다." },
      { q: "백테스트 표에서 초록 점(•)이 있는 게 더 믿을 만한가요?", a: "네. Granger 검정을 통과한 예측변수는 단순 상관관계가 아닌 시간적 선행성이 검증된 것이므로 더 신뢰할 수 있습니다." },
    ],
  },
];

// ─── Guide tab ────────────────────────────────────────────────────────────────

function GuideTab() {
  const [expandedQa, setExpandedQa] = useState<string | null>(null);
  const cats = ["성과", "통계", "방법론", "신호"] as const;

  return (
    <div className="space-y-12">
      {/* Intro banner */}
      <div className="rounded-2xl border border-[var(--accent-primary)]/15 bg-[var(--accent-primary)]/[0.04] px-6 py-5">
        <p className="mb-1.5 font-mono text-[0.60rem] uppercase tracking-[0.14em] text-[var(--accent-primary)]/60">
          처음 보시나요?
        </p>
        <p className="font-mono text-[0.78rem] leading-6 text-white/72">
          이 페이지는 뉴스 감성 데이터가 BTC 가격을 예측하는지 검증하는 분석 대시보드입니다.
        </p>
        <p className="mt-1 font-mono text-[0.68rem] leading-5 text-white/38">
          Summary → Signal → Causality → Factor 순서로 읽으시면 결과를 자연스럽게 이해할 수 있습니다.
        </p>
      </div>

      {/* Tab reading guides */}
      <div>
        <p className="mb-4 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          탭별 읽는 법
        </p>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {TAB_GUIDES.map((g) => (
            <div key={g.id} className="rounded-2xl border border-white/8 bg-white/[0.02] p-5">
              <p className="mb-1 font-mono text-[0.72rem] font-semibold text-white/82">{g.title}</p>
              <p className="mb-4 font-mono text-[0.62rem] leading-5 text-white/40">{g.summary}</p>
              <ol className="mb-4 space-y-1.5">
                {g.steps.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="mt-0.5 shrink-0 font-mono text-[0.56rem] tabular-nums text-[var(--accent-primary)]/50">
                      {i + 1}.
                    </span>
                    <span className="font-mono text-[0.60rem] leading-4 text-white/46">{s}</span>
                  </li>
                ))}
              </ol>
              <div className="space-y-2 border-t border-white/6 pt-3">
                {g.qa.map((qa, qi) => {
                  const key = `${g.id}-${qi}`;
                  const isOpen = expandedQa === key;
                  return (
                    <div key={qi}>
                      <button
                        type="button"
                        onClick={() => setExpandedQa(isOpen ? null : key)}
                        className="flex w-full cursor-pointer items-start gap-2 text-left"
                      >
                        <span className="mt-0.5 shrink-0 font-mono text-[0.54rem] text-[var(--accent-warning)]/70">
                          Q.
                        </span>
                        <span className="flex-1 font-mono text-[0.60rem] leading-4 text-white/48 transition-colors hover:text-white/66">
                          {qa.q}
                        </span>
                        <span className="shrink-0 font-mono text-[0.48rem] text-white/20">
                          {isOpen ? "▲" : "▼"}
                        </span>
                      </button>
                      {isOpen && (
                        <div className="ml-4 mt-1.5 rounded-lg border border-white/6 bg-white/[0.025] px-3 py-2">
                          <p className="font-mono text-[0.60rem] leading-5 text-white/54">{qa.a}</p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Glossary */}
      <div>
        <p className="mb-6 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
          용어 사전
        </p>
        {cats.map((cat) => {
          const entries = GLOSSARY.filter((g) => g.cat === cat);
          return (
            <div key={cat} className="mb-8">
              <div className="mb-3 flex items-center gap-3">
                <span
                  className={`rounded-full border px-3 py-0.5 font-mono text-[0.56rem] uppercase tracking-[0.10em] ${CAT_COLORS[cat]}`}
                >
                  {cat}
                </span>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {entries.map((g) => (
                  <div
                    key={g.term}
                    className="rounded-xl border border-white/6 bg-white/[0.015] px-4 py-3"
                  >
                    <div className="mb-1.5 flex items-baseline gap-2">
                      <span className="font-mono text-[0.72rem] font-semibold text-white/78">{g.term}</span>
                      {g.en && (
                        <span className="font-mono text-[0.54rem] text-white/26">{g.en}</span>
                      )}
                    </div>
                    <p className="font-mono text-[0.60rem] leading-5 text-white/44">{g.definition}</p>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── tab content ──────────────────────────────────────────────────────────────

function SummaryTab({ artifact, kpi }: { artifact: SentimentInsightArtifact; kpi: Kpi }) {
  const scatterData = useMemo(() => deriveScatter(artifact), [artifact]);

  const hitStr    = fmtPct(kpi.hitRate);
  const upliftStr = kpi.uplift !== null ? `+${(kpi.uplift * 100).toFixed(1)}pp` : "—";
  const sharpeStr = kpi.sharpe !== null ? kpi.sharpe.toFixed(2) : "—";
  const gStr      = fmtP(kpi.bestForwardP);
  const overlayLabel = kpi.overlayDecision
    ? kpi.overlayDecision.charAt(0).toUpperCase() + kpi.overlayDecision.slice(1)
    : "—";

  return (
    <div className="space-y-6">
      {/* KPI strip — 5 cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="T+7 Hit Rate"    sub="vol_regime_v2"         value={hitStr}    green />
        <KpiCard label="vs Always Long"  sub="performance uplift"    value={upliftStr} green />
        <KpiCard label="Sharpe Ratio"    sub="annualized"            value={sharpeStr} />
        <KpiCard
          label="Granger p-adj"
          sub={`Sentiment→Price lag ${kpi.bestForwardLag ?? "?"}`}
          value={gStr}
          green={kpi.bestForwardP !== null && kpi.bestForwardP < 0.05}
        />
        <KpiCard
          label="Overlay Gate"
          sub={`${kpi.overlayRecords ?? "—"}일 누적 · p=${fmtP(kpi.overlayPMedian)}`}
          value={overlayLabel}
          green={kpi.overlayAllOk && kpi.overlayDecision === "promote"}
        />
      </div>

      {/* Gate + signal evaluation status bar */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-white/8 bg-white/[0.02] px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[0.58rem] text-white/32">신호 평가</span>
          <span className="font-mono text-[0.66rem] font-semibold tabular-nums text-white/64">
            {kpi.gateTotal ?? "—"}개
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[0.58rem] text-white/32">통과 (느슨)</span>
          <span className="font-mono text-[0.66rem] font-semibold tabular-nums text-[var(--accent-green)]/80">
            {kpi.gatePromote ?? "—"}개
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[0.58rem] text-white/32">통과 (엄격)</span>
          <span
            className={`font-mono text-[0.66rem] font-semibold tabular-nums ${
              (kpi.gateStrictPromote ?? 0) > 0 ? "text-[var(--accent-green)]" : "text-[var(--accent-warning)]/70"
            }`}
          >
            {kpi.gateStrictPromote ?? "—"}개
          </span>
        </div>
        {kpi.gatePromote !== null && kpi.gateStrictPromote !== null && kpi.gatePromote !== kpi.gateStrictPromote && (
          <span className="font-mono text-[0.58rem] text-[var(--accent-warning)]/60">
            느슨/엄격 기준 불일치 — 신호 승격 보류 중
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[0.58rem] text-white/24">Rolling HR</span>
          <span className="font-mono text-[0.66rem] tabular-nums text-white/52">
            {kpi.overlayHitRate !== null ? `${(kpi.overlayHitRate * 100).toFixed(1)}%` : "—"}
          </span>
        </div>
      </div>

      {/* Charts */}
      <div className="grid gap-6 xl:grid-cols-2">
        <SignalSpaceChart data={scatterData} />
        <CausalityDirectionCard kpi={kpi} granger={artifact.granger} />
      </div>

      {/* Conclusion banner */}
      <div className="rounded-2xl border border-[var(--accent-primary)]/15 bg-[var(--accent-primary)]/[0.04] px-6 py-4">
        <p className="font-mono text-[0.72rem] leading-6 text-white/68">
          <span className="font-semibold text-[var(--accent-primary)]">결론</span>{" "}
          vol_regime_v2는 T+7 hit rate {hitStr} (Sharpe {sharpeStr})로 Always Long 대비 {upliftStr} 개선.
          Granger 인과검정에서 감성→가격 순방향 신호 확인 (p={gStr}, lag{" "}
          {kpi.bestForwardLag ?? "?"}).{" "}
          Overlay Gate: {overlayLabel} ({kpi.overlayRecords ?? "—"}일 누적, p={fmtP(kpi.overlayPMedian)}).
          taker 필터 추가 시 hit rate 79.2% 도달 가능 (n=48, 통계적으로 안정).
        </p>
      </div>
    </div>
  );
}

function SignalTab({ artifact }: { artifact: SentimentInsightArtifact }) {
  return (
    <div className="space-y-8">
      <div className="grid gap-6 xl:grid-cols-2">
        <BaselineCIChart alpha={artifact.alpha} />
        <WalkForwardTimeseries
          alpha={artifact.alpha}
          walkForward1d={artifact.alpha?.walkForwardLegacy1d}
        />
      </div>
      <SignalImprovementMatrix />
    </div>
  );
}

function CausalityTab({ artifact }: { artifact: SentimentInsightArtifact }) {
  return (
    <div className="space-y-8">
      <GrangerHeatmap granger={artifact.granger} />
      <div className="analysis-depth-panel p-5 md:p-8">
        <GrangerSymmetric granger={artifact.granger} />
      </div>
    </div>
  );
}

function FactorTab({ artifact }: { artifact: SentimentInsightArtifact }) {
  return (
    <div className="space-y-8">
      <div className="grid gap-6 xl:grid-cols-2">
        <PcaLoadingChart artifact={artifact} />
        <PcaInterpretationCard />
      </div>
      <div className="analysis-depth-panel p-5 md:p-8">
        <PcaTabs pca={artifact.pca} />
      </div>
    </div>
  );
}

function PipelineTab({
  artifact,
  diagnosticsReady,
}: {
  artifact: SentimentInsightArtifact;
  diagnosticsReady: boolean;
}) {
  return (
    <div className="space-y-8">
      <AnalysisOverviewDeck artifact={artifact} />
      <div className="analysis-depth-panel p-5 md:p-8">
        <DataQualityMatrix dataQuality={artifact.dataQuality} diagnosticsReady={diagnosticsReady} />
      </div>
      <div className="analysis-depth-panel p-5 md:p-8">
        <AlphaValidationBoard
          alpha={artifact.alpha}
          summary={artifact.summary}
          diagnosticsReady={diagnosticsReady}
          meta={artifact.meta}
        />
      </div>
      <BacktestTable alpha={artifact.alpha} />
      <div className="analysis-depth-panel p-5 md:p-8">
        <TargetDiagnosticsPanel targets={artifact.targets} diagnosticsReady={diagnosticsReady} />
      </div>
      <div className="analysis-depth-panel p-5 md:p-8">
        <StationarityPanel adf={artifact.stationarity?.adf} diagnosticsReady={diagnosticsReady} />
      </div>
      <RawMetadataExplorer rawStats={artifact.rawStats} diagnosticsReady={diagnosticsReady} />
    </div>
  );
}

// ─── main export ──────────────────────────────────────────────────────────────

export function InsightHub({
  artifact,
  diagnosticsReady,
}: {
  artifact: SentimentInsightArtifact;
  diagnosticsReady: boolean;
}) {
  const [tab, setTab] = useState<TabId>("summary");
  const kpi = useMemo(() => deriveKpi(artifact), [artifact]);

  return (
    <div className="mx-auto w-full">
      {/* Tab navigation */}
      <div className="border-b border-white/8 px-6 md:px-20">
        <div className="flex gap-0.5 overflow-x-auto py-2">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`group relative shrink-0 cursor-pointer rounded-lg px-5 py-2.5 transition-all duration-150 ${
                tab === t.id
                  ? "bg-white/8 text-white"
                  : "text-white/36 hover:bg-white/4 hover:text-white/58"
              }`}
            >
              <span className="font-mono text-[0.70rem] tracking-[0.08em]">{t.label}</span>
              <span
                className={`ml-2 font-mono text-[0.54rem] transition-opacity ${
                  tab === t.id ? "text-[var(--accent-primary)]/70 opacity-100" : "opacity-0 group-hover:opacity-60"
                }`}
              >
                {t.hint}
              </span>
              {tab === t.id && (
                <span className="absolute bottom-0.5 left-1/2 h-0.5 w-5 -translate-x-1/2 rounded-full bg-[var(--accent-primary)]" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="px-6 py-12 md:px-20">
        {tab === "summary"   && <SummaryTab   artifact={artifact} kpi={kpi} />}
        {tab === "signal"    && <SignalTab     artifact={artifact} />}
        {tab === "causality" && <CausalityTab  artifact={artifact} />}
        {tab === "factor"    && <FactorTab     artifact={artifact} />}
        {tab === "pipeline"  && <PipelineTab   artifact={artifact} diagnosticsReady={diagnosticsReady} />}
        {tab === "guide"     && <GuideTab />}
      </div>
    </div>
  );
}
