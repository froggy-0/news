import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AnalysisMasthead } from "../components/analysis/AnalysisMasthead";
import {
  AlphaValidationBoard,
  AnalysisOverviewDeck,
  DataQualityMatrix,
  RawMetadataExplorer,
  StationarityPanel,
  TargetDiagnosticsPanel,
  isFullDiagnosticArtifact,
} from "../components/analysis/AnalysisDashboardPanels";
import { GrangerSymmetric } from "../components/analysis/GrangerSymmetric";
import { PcaTabs } from "../components/analysis/PcaTabs";
import { deriveAnalysisSummary } from "../lib/analysis-derive";
import type { SentimentInsightArtifact } from "@schema/analysis.types";

const artifact: SentimentInsightArtifact = {
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
    significantGrangerCount: 2,
    grangerTestCount: 3,
    alphaCandidateCount: 2,
    baselineHorizonCount: 1,
    horizonMetricCount: 1,
    targetCount: 2,
    sourceCount: 2,
  },
  dataQuality: {
    rows: {
      beforeOutlierFilter: 365,
      afterOutlierFilter: 352,
      outlierFilteredCount: 13,
      outlierFilteredRatio: 0.0356,
    },
    ffillBreakdown: { btc: 0, usdkrw: 117, vix: 108 },
    structuredSources: {
      btc_etf: { mode: "gold_history", status: "ok" },
      futures: { mode: "supabase", status: "ok" },
    },
    exclusionCounts: { vif: 1 },
  },
  granger: {
    executed: true,
    correction: { method: "fdr_bh", nTests: 6 },
    eligibleRows: 352,
    results: [
      {
        predictor: "news_sentiment_mean",
        target: "btc_log_return",
        direction: "forward",
        lag: 1,
        pvalue: 0.02,
        pvalueAdjusted: 0.04,
        significant: true,
        optimalLag: true,
      },
      {
        predictor: "news_sentiment_mean",
        target: "btc_log_return",
        direction: "forward",
        lag: 2,
        pvalue: 0.2,
        pvalueAdjusted: 0.3,
        significant: false,
        optimalLag: false,
      },
      {
        predictor: "btc_log_return",
        target: "news_sentiment_mean",
        direction: "reverse",
        lag: 1,
        pvalue: 0.03,
        pvalueAdjusted: 0.049,
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
      selectedFeatures: ["news_sentiment_mean_lag1", "funding_rate_lag1"],
      nComponents: 1,
      explainedVariance: 0.8,
      loadings: { news_sentiment_mean_lag1: 0.6, funding_rate_lag1: -0.3 },
      excludedFeatures: [{ feature: "volume_change_pct_lag1", reason: "vif>10" }],
      coverageRatio: 0.78,
      qualityStatus: "degraded",
      qualityReasons: ["coverage_below_threshold"],
    },
    core: {
      status: "ok",
      selectedFeatures: ["news_sentiment_mean_lag1", "fng_value_lag1"],
      nComponents: 1,
      explainedVariance: 0.75,
      loadings: { news_sentiment_mean_lag1: 0.54, fng_value_lag1: 0.47 },
      excludedFeatures: [],
      coverageRatio: 0.95,
      qualityStatus: "ok",
      qualityReasons: [],
    },
  },
  alpha: {
    hitRates: [{ predictor: "news_sentiment_mean_lag1", hit_rate: 0.53, n_valid: 340 }],
    correlations: [],
    backtest: [{ predictor: "news_sentiment_mean_lag1", sharpe_ratio: 0.22, alpha: 0.014 }],
    walkForward: {},
    baselineMetrics: { "1": { always_up: { hit_rate: 0.51 } } },
    horizonMetrics: {
      "1": {
        return_col: "btc_log_return",
        hit_rates: [{ predictor: "news_sentiment_mean_lag1", hit_rate: 0.53, n_valid: 340 }],
        backtest: [{ predictor: "news_sentiment_mean_lag1", sharpe_ratio: 0.22, alpha: 0.014 }],
      },
    },
    walkForwardHorizons: {
      full: { "1": { avg_hit_rate: 0.52, stability: 0.45 } },
    },
  },
  targets: {
    diagnostics: {
      btc_large_move_3d: { valid_rows: 349, null_ratio: 0.01, positive_rate: 0.38 },
      btc_large_move_3d_vol_adj: { valid_rows: 342, null_ratio: 0.06, positive_rate: 0.16 },
    },
  },
  stationarity: {
    adf: {
      btc_log_return: { adf_stat: -8.42, pvalue: 0.0001, stationary: true },
      fng_value: { adf_stat: -2.72, pvalue: 0.071, stationary: false },
    },
  },
  rawStats: {
    ffill_breakdown: { btc: 0, usdkrw: 117 },
    target_diagnostics: { btc_large_move_3d_vol_adj: { positive_rate: 0.16 } },
  },
};

test("analysis masthead renders insight summary strip", () => {
  const markup = renderToStaticMarkup(
    createElement(AnalysisMasthead, {
      referenceDate: artifact.referenceDate,
      generatedAtUtc: artifact.generatedAtUtc,
      correction: artifact.granger.correction,
      staleWarning: false,
      summary: deriveAnalysisSummary(artifact),
      schemaVersion: artifact.schemaVersion,
      diagnosticsReady: isFullDiagnosticArtifact(artifact),
    }),
  );

  assert.match(markup, /감성이 먼저/);
  assert.match(markup, /시장이 먼저/);
  assert.match(markup, /의미 있는 관계/);
  assert.match(markup, /종합 신호 핵심/);
});

test("granger map renders forward and reverse lag rail cards", () => {
  const markup = renderToStaticMarkup(createElement(GrangerSymmetric, { granger: artifact.granger }));

  assert.match(markup, /먼저 움직인 신호/);
  assert.match(markup, /감성이 먼저/);
  assert.match(markup, /시장이 먼저/);
  assert.match(markup, /보정 p&lt;0\.05/);
  assert.match(markup, /1일 전/);
});

test("granger map renders non-executed state", () => {
  const markup = renderToStaticMarkup(
    createElement(GrangerSymmetric, {
      granger: { executed: false, correction: { method: "fdr_bh", nTests: 0 }, results: [] },
    }),
  );

  assert.match(markup, /시간 순서 검정 미수행/);
});

test("pca compass renders quality, contribution, and excluded feature context", () => {
  const markup = renderToStaticMarkup(createElement(PcaTabs, { pca: artifact.pca }));

  assert.match(markup, /지표 기여도/);
  assert.match(markup, /가장 큰 기여 지표/);
  assert.match(markup, /설명력/);
  assert.match(markup, /데이터 상태 참고 필요/);
  assert.match(markup, /함께 쓰기 어려워 제외한 지표/);
});

test("analysis dashboard panels render quality, alpha, target, stationarity, and raw views", () => {
  const markup = [
    renderToStaticMarkup(createElement(AnalysisOverviewDeck, { artifact })),
    renderToStaticMarkup(
      createElement(DataQualityMatrix, {
        dataQuality: artifact.dataQuality,
        diagnosticsReady: isFullDiagnosticArtifact(artifact),
      }),
    ),
    renderToStaticMarkup(
      createElement(AlphaValidationBoard, {
        alpha: artifact.alpha,
        summary: artifact.summary,
        diagnosticsReady: isFullDiagnosticArtifact(artifact),
      }),
    ),
    renderToStaticMarkup(
      createElement(TargetDiagnosticsPanel, {
        targets: artifact.targets,
        diagnosticsReady: isFullDiagnosticArtifact(artifact),
      }),
    ),
    renderToStaticMarkup(
      createElement(StationarityPanel, {
        adf: artifact.stationarity?.adf,
        diagnosticsReady: isFullDiagnosticArtifact(artifact),
      }),
    ),
    renderToStaticMarkup(
      createElement(RawMetadataExplorer, {
        rawStats: artifact.rawStats,
        diagnosticsReady: isFullDiagnosticArtifact(artifact),
      }),
    ),
  ].join("\n");

  assert.match(markup, /Run State/);
  assert.match(markup, /데이터 품질 매트릭스/);
  assert.match(markup, /Alpha validation/);
  assert.match(markup, /Target diagnostics/);
  assert.match(markup, /Stationarity gate/);
  assert.match(markup, /Raw parquet metadata/);
});

test("legacy v1 artifact renders pending diagnostics instead of false zeroes", () => {
  const { schemaVersion, summary, dataQuality, alpha, targets, stationarity, rawStats, ...legacy } = artifact;
  void schemaVersion;
  void summary;
  void dataQuality;
  void alpha;
  void targets;
  void stationarity;
  void rawStats;

  const legacyArtifact: SentimentInsightArtifact = legacy;
  const markup = [
    renderToStaticMarkup(createElement(AnalysisOverviewDeck, { artifact: legacyArtifact })),
    renderToStaticMarkup(
      createElement(AlphaValidationBoard, {
        alpha: legacyArtifact.alpha,
        summary: legacyArtifact.summary,
        diagnosticsReady: isFullDiagnosticArtifact(legacyArtifact),
      }),
    ),
  ].join("\n");

  assert.match(markup, /legacy v1/);
  assert.match(markup, /metadata pending/);
  assert.match(markup, /2 significant/);
  assert.match(markup, /Alpha metrics are waiting for v2 artifact/);
});

test("AlphaValidationBoard renders CI error bar markers when ci fields present", () => {
  const alphaWithCI = {
    ...artifact.alpha!,
    horizonMetrics: {
      "7": {
        return_col: "btc_log_return",
        hit_rates: [
          {
            predictor: "news_sentiment_mean_lag1",
            hit_rate: 0.61,
            hit_rate_ci_lower: 0.54,
            hit_rate_ci_upper: 0.68,
            decision: "promote",
            decision_strict: "promote",
            fdr_q: 0.07,
          },
        ],
        backtest: [],
      },
    },
  };
  const markup = renderToStaticMarkup(
    createElement(AlphaValidationBoard, {
      alpha: alphaWithCI,
      summary: artifact.summary,
      diagnosticsReady: true,
    }),
  );

  assert.match(markup, /61\.0%/);
  assert.match(markup, /q=0\.070/);
});

test("AlphaValidationBoard renders decision_strict badge on signal rows", () => {
  const alphaStrict = {
    ...artifact.alpha!,
    horizonMetrics: {
      "7": {
        return_col: "btc_log_return",
        hit_rates: [
          {
            predictor: "funding_rate_lag1",
            hit_rate: 0.58,
            decision: "promote",
            decision_strict: "hold",
            fdr_q: 0.15,
          },
        ],
        backtest: [],
      },
    },
  };
  const markup = renderToStaticMarkup(
    createElement(AlphaValidationBoard, {
      alpha: alphaStrict,
      summary: artifact.summary,
      diagnosticsReady: true,
    }),
  );

  assert.match(markup, /strict/);
  assert.match(markup, /q=0\.150/);
});

test("AlphaValidationBoard renders research rules section separately", () => {
  const alphaResearch = {
    ...artifact.alpha!,
    horizonMetrics: {
      "7": {
        return_col: "btc_log_return",
        hit_rates: [
          { predictor: "news_sentiment_mean_lag1", hit_rate: 0.61, decision: "promote", research_rule: false },
          { predictor: "etf_net_inflow_usd_log1p_lag1", hit_rate: 0.56, research_rule: true, fdr_q: 0.09, decision: "hold" },
        ] as unknown as import("@schema/analysis.types").JsonValue[],
        backtest: [],
      },
    },
  };
  const markup = renderToStaticMarkup(
    createElement(AlphaValidationBoard, {
      alpha: alphaResearch as unknown as import("@schema/analysis.types").AlphaSection,
      summary: artifact.summary,
      diagnosticsReady: true,
    }),
  );

  assert.match(markup, /Research rules/);
  assert.match(markup, /research/);
  assert.match(markup, /etf.net.inflow/i);
});

test("AlphaValidationBoard renders gate stats when gateStats present in horizonMetrics", () => {
  const alphaGate = {
    ...artifact.alpha!,
    gateStats: {
      totalPredictors: 8,
      decisionPromoteCount: 3,
      decisionStrictPromoteCount: 2,
      gap: 1,
      gapRatio: 0.3333,
    },
  };
  const markup = renderToStaticMarkup(
    createElement(AlphaValidationBoard, {
      alpha: alphaGate,
      summary: artifact.summary,
      diagnosticsReady: true,
    }),
  );

  assert.match(markup, /decision.*strict/i);
  assert.match(markup, /3 promote/);
  assert.match(markup, /2 promote/);
});

test("AlphaValidationBoard renders Sharpe annualization change notice when meta present", () => {
  const meta = {
    annualizationFactor: 365,
    annualizationNote:
      "Sharpe는 sqrt(365) 기준으로 연환산됩니다. 2026-04-30 이전 산출물은 sqrt(252) 기준이므로 직접 비교 불가합니다.",
    sharpeBasisChangeDate: "2026-04-30",
  };
  const markup = renderToStaticMarkup(
    createElement(AlphaValidationBoard, {
      alpha: artifact.alpha,
      summary: artifact.summary,
      diagnosticsReady: true,
      meta,
    }),
  );

  assert.match(markup, /Sharpe basis changed/i);
  assert.match(markup, /2026-04-30/);
  assert.match(markup, /sqrt\(252\)/);
});

test("AlphaValidationBoard does not render Sharpe notice when meta absent", () => {
  const markup = renderToStaticMarkup(
    createElement(AlphaValidationBoard, {
      alpha: artifact.alpha,
      summary: artifact.summary,
      diagnosticsReady: true,
    }),
  );

  assert.doesNotMatch(markup, /Sharpe basis changed/i);
});

