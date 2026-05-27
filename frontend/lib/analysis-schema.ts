import type {
  AlphaSection,
  ArtifactSummary,
  DataQualityRows,
  DataQualitySection,
  ExcludedFeature,
  GrangerCorrection,
  GrangerResult,
  GrangerSection,
  GrangerSkip,
  JsonObject,
  JsonValue,
  PcaIndex,
  PcaSection,
  SentimentInsightArtifact,
  StationaritySection,
  TargetsSection,
} from "@schema/analysis.types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, name: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${name} must be an object`);
  }
  return value;
}

function requireString(value: unknown, name: string): string {
  if (typeof value !== "string") {
    throw new Error(`${name} must be a string`);
  }
  return value;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number") return value;
  return null;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return null;
}

function asBoolean(value: unknown): boolean {
  return value === true;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function toJsonValue(value: unknown): JsonValue {
  if (value === null) return null;
  if (typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return value.map(toJsonValue);
  if (isRecord(value)) {
    const result: JsonObject = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = toJsonValue(item);
    }
    return result;
  }
  return String(value);
}

function toJsonObject(value: unknown): JsonObject {
  const converted = toJsonValue(value);
  return isRecord(converted) ? converted : {};
}

function toJsonArray(value: unknown): JsonValue[] {
  const converted = toJsonValue(value);
  return Array.isArray(converted) ? converted : [];
}

function parseExcludedFeature(value: unknown): ExcludedFeature {
  if (!isRecord(value)) return { feature: "", reason: "" };
  return {
    feature: typeof value.feature === "string" ? value.feature : "",
    reason: typeof value.reason === "string" ? value.reason : "",
  };
}

function parseGrangerSkip(value: unknown): GrangerSkip {
  if (!isRecord(value)) {
    return {
      predictor: "",
      target: "",
      direction: "",
      reason: "unknown",
      rowsBeforeStationarity: null,
      rowsAfterStationarity: null,
      message: "",
    };
  }
  return {
    predictor: typeof value.predictor === "string" ? value.predictor : "",
    target: typeof value.target === "string" ? value.target : "",
    direction: typeof value.direction === "string" ? value.direction : "",
    reason: typeof value.reason === "string" ? value.reason : "unknown",
    rowsBeforeStationarity: asFiniteNumber(value.rowsBeforeStationarity),
    rowsAfterStationarity: asFiniteNumber(value.rowsAfterStationarity),
    message: typeof value.message === "string" ? value.message : "",
  };
}

function parseGrangerResult(value: unknown, index: number): GrangerResult {
  const raw = requireRecord(value, `granger.results[${index}]`);
  const predictor = requireString(raw.predictor, `granger.results[${index}].predictor`);
  const target = requireString(raw.target, `granger.results[${index}].target`);
  const direction = raw.direction === "reverse" ? "reverse" : ("forward" as const);

  if (typeof raw.lag !== "number") {
    throw new Error(`granger.results[${index}].lag must be a number`);
  }

  return {
    predictor,
    target,
    direction,
    lag: raw.lag,
    pvalue: asNumber(raw.pvalue),
    pvalueAdjusted: asNumber(raw.pvalueAdjusted),
    fStatistic: asNumber(raw.fStatistic) ?? asNumber(raw.f_statistic),
    significant: asBoolean(raw.significant),
    optimalLag: asBoolean(raw.optimalLag),
  };
}

function parseGrangerCorrection(value: unknown): GrangerCorrection {
  const raw = requireRecord(value, "granger.correction");
  return {
    method: typeof raw.method === "string" ? raw.method : "fdr_bh",
    nTests: typeof raw.nTests === "number" ? raw.nTests : 0,
  };
}

function parseGrangerSection(value: unknown): GrangerSection {
  const raw = requireRecord(value, "granger");
  const executed = asBoolean(raw.executed);
  const correction = parseGrangerCorrection(raw.correction);
  const resultsRaw = Array.isArray(raw.results) ? raw.results : [];
  const results = resultsRaw.map((item, i) => parseGrangerResult(item, i));
  const skipsRaw = Array.isArray(raw.skips) ? raw.skips : [];

  return {
    executed,
    correction,
    eligibleRows: asFiniteNumber(raw.eligibleRows),
    results,
    skips: skipsRaw.map(parseGrangerSkip),
    skipSummary: toJsonObject(raw.skipSummary),
  };
}

function parsePcaIndex(value: unknown, name: string): PcaIndex {
  const raw = requireRecord(value, name);
  const loadingsRaw = isRecord(raw.loadings) ? raw.loadings : {};
  const loadings: Record<string, number> = {};
  for (const [k, v] of Object.entries(loadingsRaw)) {
    if (typeof v === "number") loadings[k] = v;
  }

  const excludedRaw = Array.isArray(raw.excludedFeatures) ? raw.excludedFeatures : [];
  const qualityStatus = typeof raw.qualityStatus === "string" ? raw.qualityStatus : "degraded";

  return {
    status: typeof raw.status === "string" ? raw.status : "unknown",
    selectedFeatures: asStringArray(raw.selectedFeatures),
    nComponents: typeof raw.nComponents === "number" ? raw.nComponents : 0,
    explainedVariance: typeof raw.explainedVariance === "number" ? raw.explainedVariance : 0,
    loadings,
    excludedFeatures: excludedRaw.map(parseExcludedFeature),
    coverageRatio: typeof raw.coverageRatio === "number" ? raw.coverageRatio : 0,
    qualityStatus,
    qualityReasons: asStringArray(raw.qualityReasons),
  };
}

function parsePcaSection(value: unknown): PcaSection {
  const raw = requireRecord(value, "pca");
  return {
    full: parsePcaIndex(raw.full, "pca.full"),
    core: parsePcaIndex(raw.core, "pca.core"),
  };
}

function parseArtifactSummary(value: unknown): ArtifactSummary {
  const raw = isRecord(value) ? value : {};
  return {
    rowsBeforeOutlierFilter: asFiniteNumber(raw.rowsBeforeOutlierFilter),
    rowsAfterOutlierFilter: asFiniteNumber(raw.rowsAfterOutlierFilter),
    outlierFilteredCount: asFiniteNumber(raw.outlierFilteredCount),
    outlierFilteredRatio: asFiniteNumber(raw.outlierFilteredRatio),
    grangerEligibleRows: asFiniteNumber(raw.grangerEligibleRows),
    grangerExecuted: asBoolean(raw.grangerExecuted),
    significantGrangerCount: asFiniteNumber(raw.significantGrangerCount) ?? 0,
    grangerTestCount: asFiniteNumber(raw.grangerTestCount) ?? 0,
    alphaCandidateCount: asFiniteNumber(raw.alphaCandidateCount) ?? 0,
    baselineHorizonCount: asFiniteNumber(raw.baselineHorizonCount) ?? 0,
    horizonMetricCount: asFiniteNumber(raw.horizonMetricCount) ?? 0,
    targetCount: asFiniteNumber(raw.targetCount) ?? 0,
    sourceCount: asFiniteNumber(raw.sourceCount) ?? 0,
  };
}

function parseDataQualityRows(value: unknown): DataQualityRows {
  const raw = isRecord(value) ? value : {};
  return {
    beforeOutlierFilter: asFiniteNumber(raw.beforeOutlierFilter),
    afterOutlierFilter: asFiniteNumber(raw.afterOutlierFilter),
    outlierFilteredCount: asFiniteNumber(raw.outlierFilteredCount),
    outlierFilteredRatio: asFiniteNumber(raw.outlierFilteredRatio),
  };
}

function parseDataQualitySection(value: unknown): DataQualitySection {
  const raw = isRecord(value) ? value : {};
  return {
    rows: parseDataQualityRows(raw.rows),
    ffillBreakdown: toJsonObject(raw.ffillBreakdown),
    structuredSources: toJsonObject(raw.structuredSources),
    exclusionCounts: toJsonObject(raw.exclusionCounts),
  };
}

function parseAlphaSection(value: unknown): AlphaSection {
  const raw = isRecord(value) ? value : {};
  const bootstrapRaw = raw.bootstrapConfig ?? raw.bootstrap_config;
  const gateStatsRaw = raw.gateStats ?? raw.gate_stats;
  const promotionGateRaw = raw.promotionGate ?? raw.promotion_gate;
  const walkForwardLegacy1dRaw = raw.walkForwardLegacy1d ?? raw.walk_forward_legacy_1d;
  return {
    hitRates: toJsonArray(raw.hitRates),
    correlations: toJsonArray(raw.correlations),
    backtest: toJsonArray(raw.backtest),
    walkForward: toJsonObject(raw.walkForward),
    walkForwardLegacy1d: walkForwardLegacy1dRaw === undefined ? undefined : toJsonObject(walkForwardLegacy1dRaw),
    baselineMetrics: toJsonObject(raw.baselineMetrics),
    horizonMetrics: toJsonObject(raw.horizonMetrics),
    walkForwardHorizons: toJsonObject(raw.walkForwardHorizons),
    bootstrapConfig: bootstrapRaw === undefined ? undefined : toJsonObject(bootstrapRaw),
    gateStats: gateStatsRaw === undefined ? undefined : toJsonObject(gateStatsRaw),
    promotionGate: promotionGateRaw === undefined ? undefined : toJsonObject(promotionGateRaw),
  };
}

function parseTargetsSection(value: unknown): TargetsSection {
  const raw = isRecord(value) ? value : {};
  return { diagnostics: toJsonObject(raw.diagnostics) };
}

function parseStationaritySection(value: unknown): StationaritySection {
  const raw = isRecord(value) ? value : {};
  return { adf: toJsonObject(raw.adf) };
}

export function parseSentimentInsight(value: unknown): SentimentInsightArtifact {
  const raw = requireRecord(value, "SentimentInsightArtifact");
  const schemaVersion = typeof raw.schemaVersion === "string" ? raw.schemaVersion : undefined;
  const generatedAtUtc = requireString(raw.generatedAtUtc, "generatedAtUtc");
  const referenceDate = requireString(raw.referenceDate, "referenceDate");
  const runId = requireString(raw.runId, "runId");
  const summary = parseArtifactSummary(raw.summary);
  const dataQuality = parseDataQualitySection(raw.dataQuality);
  const granger = parseGrangerSection(raw.granger);
  const pca = parsePcaSection(raw.pca);
  const alpha = parseAlphaSection(raw.alpha);
  const targets = parseTargetsSection(raw.targets);
  const stationarity = parseStationaritySection(raw.stationarity);
  const rawStats = toJsonObject(raw.rawStats);

  const meta = isRecord(raw.meta) ? toJsonObject(raw.meta) : undefined;

  return {
    schemaVersion,
    generatedAtUtc,
    referenceDate,
    runId,
    summary,
    dataQuality,
    granger,
    pca,
    alpha,
    targets,
    stationarity,
    rawStats,
    meta,
  };
}
