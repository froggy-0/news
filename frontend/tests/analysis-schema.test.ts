import test from "node:test";
import assert from "node:assert/strict";

import { parseSentimentInsight } from "../lib/analysis-schema";

const validPayload = {
  generatedAtUtc: "2026-04-21T08:00:00+00:00",
  referenceDate: "2026-04-21",
  runId: "sentiment-join-20260421",
  granger: {
    executed: true,
    correction: { method: "fdr_bh", nTests: 63 },
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
};

test("parseSentimentInsight: 유효한 payload → SentimentInsightArtifact 반환", () => {
  const result = parseSentimentInsight(validPayload);
  assert.equal(result.referenceDate, "2026-04-21");
  assert.equal(result.granger.executed, true);
  assert.equal(result.granger.results.length, 1);
  assert.equal(result.granger.results[0].direction, "forward");
  assert.equal(result.granger.results[0].optimalLag, true);
  assert.equal(result.pca.full.explainedVariance, 0.802);
  assert.equal(result.pca.core.coverageRatio, 0.95);
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
