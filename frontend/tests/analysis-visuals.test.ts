import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AnalysisMasthead } from "../components/analysis/AnalysisMasthead";
import { GrangerSymmetric } from "../components/analysis/GrangerSymmetric";
import { PcaTabs } from "../components/analysis/PcaTabs";
import { deriveAnalysisSummary } from "../lib/analysis-derive";
import type { SentimentInsightArtifact } from "@schema/analysis.types";

const artifact: SentimentInsightArtifact = {
  generatedAtUtc: "2026-04-21T08:00:00+00:00",
  referenceDate: "2026-04-21",
  runId: "sentiment-join-20260421",
  granger: {
    executed: true,
    correction: { method: "fdr_bh", nTests: 6 },
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
};

test("analysis masthead renders insight summary strip", () => {
  const markup = renderToStaticMarkup(
    createElement(AnalysisMasthead, {
      referenceDate: artifact.referenceDate,
      generatedAtUtc: artifact.generatedAtUtc,
      correction: artifact.granger.correction,
      staleWarning: false,
      summary: deriveAnalysisSummary(artifact),
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
