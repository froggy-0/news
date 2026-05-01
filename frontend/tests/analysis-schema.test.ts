import test from "node:test";
import assert from "node:assert/strict";

import { parseSentimentInsight } from "../lib/analysis-schema";

const validPayload = {
  schemaVersion: "sentiment-insight-v2",
  generatedAtUtc: "2026-04-21T08:00:00+00:00",
  referenceDate: "2026-04-21",
  runId: "sentiment-join-20260421",
  summary: {
    rowsBeforeOutlierFilter: 365,
    rowsAfterOutlierFilter: 352,
    outlierFilteredCount: 13,
    outlierFilteredRatio: 0.0356,
    grangerEligibleRows: 352,
    grangerExecuted: true,
    significantGrangerCount: 1,
    grangerTestCount: 1,
    alphaCandidateCount: 1,
    baselineHorizonCount: 1,
    horizonMetricCount: 1,
    targetCount: 2,
    sourceCount: 1,
  },
  dataQuality: {
    rows: {
      beforeOutlierFilter: 365,
      afterOutlierFilter: 352,
      outlierFilteredCount: 13,
      outlierFilteredRatio: 0.0356,
    },
    ffillBreakdown: { btc: 0, usdkrw: 117 },
    structuredSources: { btc_etf: { mode: "gold_history" } },
    exclusionCounts: { vif: 1 },
  },
  granger: {
    executed: true,
    correction: { method: "fdr_bh", nTests: 63 },
    eligibleRows: 352,
    results: [
      {
        predictor: "news_sentiment_mean",
        target: "fng_value",
        direction: "forward",
        lag: 1,
        pvalue: 0.03,
        pvalueAdjusted: 0.045,
        significant: true,
        optimalLag: true,
      },
    ],
    skips: [],
    skipSummary: {},
  },
  pca: {
    full: {
      status: "ok",
      selectedFeatures: ["news_sentiment_mean_lag1"],
      nComponents: 1,
      explainedVariance: 0.802,
      loadings: { news_sentiment_mean_lag1: 0.528 },
      excludedFeatures: [],
      coverageRatio: 0.91,
      qualityStatus: "ok",
      qualityReasons: [],
    },
    core: {
      status: "ok",
      selectedFeatures: ["news_sentiment_mean_lag1"],
      nComponents: 1,
      explainedVariance: 0.751,
      loadings: { news_sentiment_mean_lag1: 0.542 },
      excludedFeatures: [],
      coverageRatio: 0.95,
      qualityStatus: "ok",
      qualityReasons: [],
    },
  },
  alpha: {
    hitRates: [{ predictor: "news_sentiment_mean_lag1", hit_rate: 0.53 }],
    correlations: [],
    backtest: [],
    walkForward: {},
    baselineMetrics: { "1": { always_up: { hit_rate: 0.51 } } },
    horizonMetrics: { "1": { return_col: "btc_log_return", hit_rates: [], backtest: [] } },
    walkForwardHorizons: {},
  },
  targets: {
    diagnostics: {
      btc_large_move_3d: { positive_rate: 0.38 },
      btc_large_move_3d_vol_adj: { positive_rate: 0.16 },
    },
  },
  stationarity: {
    adf: { btc_log_return: { pvalue: 0.01, stationary: true } },
  },
  rawStats: {
    structured_sources: { btc_etf: { mode: "gold_history" } },
  },
};

test("parseSentimentInsight: 유효한 payload → SentimentInsightArtifact 반환", () => {
  const result = parseSentimentInsight(validPayload);
  assert.equal(result.referenceDate, "2026-04-21");
  assert.equal(result.schemaVersion, "sentiment-insight-v2");
  assert.equal(result.granger.executed, true);
  assert.equal(result.granger.eligibleRows, 352);
  assert.equal(result.granger.results.length, 1);
  assert.equal(result.granger.results[0].direction, "forward");
  assert.equal(result.granger.results[0].optimalLag, true);
  assert.equal(result.pca.full.explainedVariance, 0.802);
  assert.equal(result.pca.core.coverageRatio, 0.95);
  assert.equal(result.summary?.rowsAfterOutlierFilter, 352);
  assert.equal(result.dataQuality?.ffillBreakdown.usdkrw, 117);
  assert.deepEqual(result.alpha?.baselineMetrics["1"], validPayload.alpha.baselineMetrics["1"]);
  assert.deepEqual(
    result.targets?.diagnostics.btc_large_move_3d_vol_adj,
    validPayload.targets.diagnostics.btc_large_move_3d_vol_adj,
  );
  assert.deepEqual(result.stationarity?.adf.btc_log_return, validPayload.stationarity.adf.btc_log_return);
  assert.deepEqual(result.rawStats?.structured_sources, validPayload.rawStats.structured_sources);
});

test("parseSentimentInsight: v1 payload도 신규 dashboard 필드 기본값을 채운다", () => {
  const { schemaVersion, summary, dataQuality, alpha, targets, stationarity, rawStats, ...v1Payload } = validPayload;
  void schemaVersion;
  void summary;
  void dataQuality;
  void alpha;
  void targets;
  void stationarity;
  void rawStats;

  const result = parseSentimentInsight(v1Payload);
  assert.equal(result.summary?.alphaCandidateCount, 0);
  assert.deepEqual(result.dataQuality?.ffillBreakdown, {});
  assert.deepEqual(result.alpha?.hitRates, []);
  assert.deepEqual(result.targets?.diagnostics, {});
  assert.deepEqual(result.rawStats, {});
});

test("parseSentimentInsight: generatedAtUtc 누락 → throw", () => {
  const bad = { ...validPayload, generatedAtUtc: undefined };
  assert.throws(() => parseSentimentInsight(bad), /generatedAtUtc must be a string/);
});

test("parseSentimentInsight: referenceDate 누락 → throw", () => {
  const bad = { ...validPayload, referenceDate: undefined };
  assert.throws(() => parseSentimentInsight(bad), /referenceDate must be a string/);
});

test("parseSentimentInsight: runId 누락 → throw", () => {
  const bad = { ...validPayload, runId: undefined };
  assert.throws(() => parseSentimentInsight(bad), /runId must be a string/);
});

test("parseSentimentInsight: granger 누락 → throw", () => {
  const bad = { ...validPayload, granger: undefined };
  assert.throws(() => parseSentimentInsight(bad), /granger must be an object/);
});

test("parseSentimentInsight: pca 누락 → throw", () => {
  const bad = { ...validPayload, pca: undefined };
  assert.throws(() => parseSentimentInsight(bad), /pca must be an object/);
});

test("parseSentimentInsight: granger.results[].lag 누락 → throw", () => {
  const bad = {
    ...validPayload,
    granger: {
      ...validPayload.granger,
      results: [{ ...validPayload.granger.results[0], lag: "not-a-number" }],
    },
  };
  assert.throws(() => parseSentimentInsight(bad), /lag must be a number/);
});

test("parseSentimentInsight: direction 'reverse' 보존", () => {
  const payload = {
    ...validPayload,
    granger: {
      ...validPayload.granger,
      results: [{ ...validPayload.granger.results[0], direction: "reverse" }],
    },
  };
  const result = parseSentimentInsight(payload);
  assert.equal(result.granger.results[0].direction, "reverse");
});

test("parseSentimentInsight: excludedFeatures dict 형식 파싱", () => {
  const payload = {
    ...validPayload,
    pca: {
      ...validPayload.pca,
      full: {
        ...validPayload.pca.full,
        excludedFeatures: [{ feature: "volume_lag1", reason: "vif>10" }],
      },
    },
  };
  const result = parseSentimentInsight(payload);
  assert.equal(result.pca.full.excludedFeatures[0].feature, "volume_lag1");
  assert.equal(result.pca.full.excludedFeatures[0].reason, "vif>10");
});

test("parseSentimentInsight: alpha.gateStats and meta are parsed", () => {
  const payload = {
    ...validPayload,
    alpha: {
      ...validPayload.alpha,
      gateStats: { decisionPromoteCount: 4, decisionStrictPromoteCount: 3, gap: 1, gapRatio: 0.25 },
    },
    meta: { annualizationFactor: 365, sharpeBasisChangeDate: "2026-04-30" },
  };
  const result = parseSentimentInsight(payload);
  assert.equal(result.alpha?.gateStats?.decisionPromoteCount, 4);
  assert.equal(result.alpha?.gateStats?.gapRatio, 0.25);
  assert.equal(result.meta?.annualizationFactor, 365);
  assert.equal(result.meta?.sharpeBasisChangeDate, "2026-04-30");
});

test("parseSentimentInsight: meta 누락 시 undefined 반환", () => {
  const result = parseSentimentInsight(validPayload);
  assert.equal(result.meta, undefined);
});
