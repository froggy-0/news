import type {
  GrangerDirection,
  GrangerResult,
  PcaIndex,
  SentimentInsightArtifact,
} from "@schema/analysis.types";

export type DerivedSignal = {
  label: string;
  predictor: string;
  target: string;
  lag: number | null;
  adjustedPValue: number | null;
  significant: boolean;
};

export type DerivedPcaDriver = {
  feature: string;
  label: string;
  loading: number;
  direction: "positive" | "negative";
};

export type AnalysisSummary = {
  strongestForward: DerivedSignal | null;
  strongestReverse: DerivedSignal | null;
  significantCount: number;
  topPcaDriver: DerivedPcaDriver | null;
  qualityStatus: string;
  coverageRatio: number;
};

export type GrangerRawStatistic = {
  predictor: string;
  target: string;
  direction: GrangerDirection;
  lag: number;
  fStatistic: number | null;
  pvalue: number | null;
  pvalueAdjusted: number | null;
  significant: boolean;
  primary: boolean;
  optimalLag: number | null;
};

export type NewsBtcGrangerAsymmetry = {
  lag: number;
  forward: GrangerRawStatistic | null;
  reverse: GrangerRawStatistic | null;
  primaryForward: GrangerRawStatistic | null;
  primaryReverse: GrangerRawStatistic | null;
  ratio: number | null;
};

function cleanFeatureName(value: string): string {
  return value.replace(/_lag\d+$/, "").replace(/_mean$/, "").replace(/_/g, " ");
}

export function formatFeatureLabel(value: string): string {
  const cleaned = cleanFeatureName(value);
  const labels: Record<string, string> = {
    "news sentiment": "News Sentiment",
    "btc log return": "BTC Log Return",
    "btc return": "BTC Price Change",
    "fng value": "Fear & Greed Index",
    "funding rate": "Funding Rate",
    "volume change pct": "Volume Change",
    "btc long short ratio": "Long/Short Ratio",
    "etf net inflow usd": "ETF Net Inflow",
    "vix": "VIX Volatility",
    "sentiment momentum": "Sentiment Momentum",
    "sentiment accel": "Sentiment Accel",
    "fng change 1d": "F&G Change 1d",
    "fng change 5d": "F&G Change 5d",
    "btc bear regime": "BTC Bear Regime",
    "sentiment momentum x bear": "Bear Sentiment Momentum",
    "fng change 1d x bear": "Bear F&G Change",
    "funding rate x bear": "Bear Funding Rate",
    "full hybrid index score": "Extended Index Score",
    "core hybrid index score": "Core Index Score",
  };
  return labels[cleaned] ?? cleaned;
}

export function formatSignalLabel(result: Pick<GrangerResult, "predictor" | "target">): string {
  return `${formatFeatureLabel(result.predictor)} -> ${formatFeatureLabel(result.target)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function deriveRawGrangerStatistics(
  artifact: Pick<SentimentInsightArtifact, "rawStats">,
): GrangerRawStatistic[] {
  const rows = artifact.rawStats?.granger_results;
  if (!Array.isArray(rows)) return [];

  return rows.flatMap((item): GrangerRawStatistic[] => {
    if (!isRecord(item)) return [];
    const predictor = textValue(item.predictor);
    const target = textValue(item.target);
    const lag = finiteNumber(item.lag);
    if (!predictor || !target || lag === null) return [];

    const rawDirection = textValue(item.direction);
    const direction: GrangerDirection = rawDirection === "reverse" ? "reverse" : "forward";

    return [
      {
        predictor,
        target,
        direction,
        lag,
        fStatistic: finiteNumber(item.f_statistic) ?? finiteNumber(item.fStatistic),
        pvalue: finiteNumber(item.pvalue) ?? finiteNumber(item.pvalue_raw),
        pvalueAdjusted: finiteNumber(item.pvalue_adjusted) ?? finiteNumber(item.pvalueAdjusted),
        significant: item.significant === true,
        primary: item.granger_primary === true || item.primary === true,
        optimalLag: finiteNumber(item.optimal_lag) ?? finiteNumber(item.optimalLag),
      },
    ];
  });
}

function findRawGrangerStatistic(
  rows: GrangerRawStatistic[],
  predictor: string,
  target: string,
  lag?: number,
): GrangerRawStatistic | null {
  const candidates = rows.filter((row) => row.predictor === predictor && row.target === target);
  if (lag !== undefined) return candidates.find((row) => row.lag === lag) ?? null;

  return (
    candidates.find((row) => row.primary) ??
    [...candidates].sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1))[0] ??
    null
  );
}

export function deriveNewsBtcGrangerAsymmetry(
  artifact: Pick<SentimentInsightArtifact, "rawStats">,
  lag = 1,
): NewsBtcGrangerAsymmetry {
  const rows = deriveRawGrangerStatistics(artifact);
  const forward = findRawGrangerStatistic(rows, "news_sentiment_mean", "btc_log_return", lag);
  const reverse = findRawGrangerStatistic(rows, "btc_log_return", "news_sentiment_mean", lag);
  const primaryForward = findRawGrangerStatistic(rows, "news_sentiment_mean", "btc_log_return");
  const primaryReverse = findRawGrangerStatistic(rows, "btc_log_return", "news_sentiment_mean");
  const ratio =
    forward?.fStatistic && reverse?.fStatistic && forward.fStatistic > 0
      ? reverse.fStatistic / forward.fStatistic
      : null;

  return { lag, forward, reverse, primaryForward, primaryReverse, ratio };
}

export function negLog10(value: number | null): number {
  if (value === null || value <= 0) return 0;
  return -Math.log10(Math.min(value, 1));
}

export function formatQValue(value: number | null): string {
  return formatAdjustedPValue(value);
}

export function formatAdjustedPValue(value: number | null): string {
  if (value === null) return "보정 p 없음";
  if (value < 0.001) return "보정 p<0.001";
  return `보정 p=${value.toFixed(3)}`;
}

export function formatQualityStatus(value: string): string {
  if (value === "ok") return "OK";
  if (value === "degraded") return "Degraded";
  if (value === "critical") return "Critical";
  return value;
}

export function formatQualityReason(value: string): string {
  const reasons: Record<string, string> = {
    coverage_below_threshold: "Coverage below threshold",
    missing_full_expansion_features: "Some extended features missing",
    btc_etf_history_unavailable: "Insufficient ETF history",
    futures_oi_incomplete: "Futures open interest data incomplete",
    futures_lsr_incomplete: "Long/short ratio data incomplete",
    futures_funding_incomplete: "Funding rate data incomplete",
  };
  if (value.toLowerCase().startsWith("vif")) {
    return "Excluded — too collinear with another feature";
  }
  return reasons[value] ?? value.replace(/_/g, " ");
}

function groupKey(result: GrangerResult): string {
  return `${result.predictor}||${result.target}||${result.direction}`;
}

export function bestSignalsByDirection(
  results: GrangerResult[],
  direction: GrangerDirection,
): DerivedSignal | null {
  const groups = new Map<string, GrangerResult[]>();
  for (const result of results) {
    if (result.direction !== direction) continue;
    const key = groupKey(result);
    groups.set(key, [...(groups.get(key) ?? []), result]);
  }

  const candidates = [...groups.values()].map((items) => {
    const sorted = [...items].sort((a, b) => {
      if (a.optimalLag !== b.optimalLag) return a.optimalLag ? -1 : 1;
      return (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1);
    });
    return sorted[0];
  });

  candidates.sort((a, b) => {
    if (a.significant !== b.significant) return a.significant ? -1 : 1;
    return (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1);
  });

  const best = candidates[0];
  if (!best) return null;

  return {
    label: formatSignalLabel(best),
    predictor: best.predictor,
    target: best.target,
    lag: best.lag,
    adjustedPValue: best.pvalueAdjusted,
    significant: best.significant,
  };
}

export function topPcaDriver(index: PcaIndex): DerivedPcaDriver | null {
  const [feature, loading] =
    Object.entries(index.loadings).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0] ?? [];
  if (!feature || typeof loading !== "number") return null;

  return {
    feature,
    label: formatFeatureLabel(feature),
    loading,
    direction: loading >= 0 ? "positive" : "negative",
  };
}

function dominantQuality(full: PcaIndex, core: PcaIndex): string {
  if (full.qualityStatus === "critical" || core.qualityStatus === "critical") return "critical";
  if (full.qualityStatus === "degraded" || core.qualityStatus === "degraded") return "degraded";
  return "ok";
}

export function deriveAnalysisSummary(artifact: SentimentInsightArtifact): AnalysisSummary {
  return {
    strongestForward: artifact.granger.executed
      ? bestSignalsByDirection(artifact.granger.results, "forward")
      : null,
    strongestReverse: artifact.granger.executed
      ? bestSignalsByDirection(artifact.granger.results, "reverse")
      : null,
    significantCount: artifact.granger.results.filter((result) => result.significant).length,
    topPcaDriver: topPcaDriver(artifact.pca.core) ?? topPcaDriver(artifact.pca.full),
    qualityStatus: dominantQuality(artifact.pca.full, artifact.pca.core),
    coverageRatio: Math.max(artifact.pca.full.coverageRatio, artifact.pca.core.coverageRatio),
  };
}


export function isFullDiagnosticArtifact(artifact: SentimentInsightArtifact): boolean {
  return (
    artifact.schemaVersion === "sentiment-insight-v2" &&
    Object.keys(artifact.rawStats ?? {}).length > 0
  );
}
