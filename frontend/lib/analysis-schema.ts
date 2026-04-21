import type {
  ExcludedFeature,
  GrangerCorrection,
  GrangerResult,
  GrangerSection,
  PcaIndex,
  PcaSection,
  SentimentInsightArtifact,
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

function asBoolean(value: unknown): boolean {
  return value === true;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function parseExcludedFeature(value: unknown): ExcludedFeature {
  if (!isRecord(value)) return { feature: "", reason: "" };
  return {
    feature: typeof value.feature === "string" ? value.feature : "",
    reason: typeof value.reason === "string" ? value.reason : "",
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

  return { executed, correction, results };
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

export function parseSentimentInsight(value: unknown): SentimentInsightArtifact {
  const raw = requireRecord(value, "SentimentInsightArtifact");
  const generatedAtUtc = requireString(raw.generatedAtUtc, "generatedAtUtc");
  const referenceDate = requireString(raw.referenceDate, "referenceDate");
  const runId = requireString(raw.runId, "runId");
  const granger = parseGrangerSection(raw.granger);
  const pca = parsePcaSection(raw.pca);

  return { generatedAtUtc, referenceDate, runId, granger, pca };
}
