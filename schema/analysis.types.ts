export type GrangerDirection = "forward" | "reverse";

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface GrangerResult {
  predictor: string;
  target: string;
  direction: GrangerDirection;
  lag: number;
  pvalue: number | null;
  pvalueAdjusted: number | null;
  significant: boolean;
  optimalLag: boolean;
}

export interface GrangerCorrection {
  method: string;
  nTests: number;
}

export interface GrangerSkip {
  predictor: string;
  target: string;
  direction: string;
  reason: string;
  rowsBeforeStationarity: number | null;
  rowsAfterStationarity: number | null;
  message: string;
}

export interface GrangerSection {
  executed: boolean;
  correction: GrangerCorrection;
  eligibleRows?: number | null;
  results: GrangerResult[];
  skips?: GrangerSkip[];
  skipSummary?: JsonObject;
}

export interface ExcludedFeature {
  feature: string;
  reason: string;
}

export interface PcaIndex {
  status: string;
  selectedFeatures: string[];
  nComponents: number;
  explainedVariance: number;
  loadings: Record<string, number>;
  excludedFeatures: ExcludedFeature[];
  coverageRatio: number;
  qualityStatus: "ok" | "degraded" | "critical" | string;
  qualityReasons: string[];
}

export interface PcaSection {
  full: PcaIndex;
  core: PcaIndex;
}

export interface ArtifactSummary {
  rowsBeforeOutlierFilter: number | null;
  rowsAfterOutlierFilter: number | null;
  outlierFilteredCount: number | null;
  outlierFilteredRatio: number | null;
  grangerEligibleRows: number | null;
  grangerExecuted: boolean;
  significantGrangerCount: number;
  grangerTestCount: number;
  alphaCandidateCount: number;
  baselineHorizonCount: number;
  horizonMetricCount: number;
  targetCount: number;
  sourceCount: number;
}

export interface DataQualityRows {
  beforeOutlierFilter: number | null;
  afterOutlierFilter: number | null;
  outlierFilteredCount: number | null;
  outlierFilteredRatio: number | null;
}

export interface DataQualitySection {
  rows: DataQualityRows;
  ffillBreakdown: JsonObject;
  structuredSources: JsonObject;
  exclusionCounts: JsonObject;
}

export interface AlphaSection {
  hitRates: JsonValue[];
  correlations: JsonValue[];
  backtest: JsonValue[];
  walkForward: JsonObject;
  baselineMetrics: JsonObject;
  horizonMetrics: JsonObject;
  walkForwardHorizons: JsonObject;
}

export interface TargetsSection {
  diagnostics: JsonObject;
}

export interface StationaritySection {
  adf: JsonObject;
}

export interface SentimentInsightArtifact {
  schemaVersion?: string;
  generatedAtUtc: string;
  referenceDate: string;
  runId: string;
  summary?: ArtifactSummary;
  dataQuality?: DataQualitySection;
  granger: GrangerSection;
  pca: PcaSection;
  alpha?: AlphaSection;
  targets?: TargetsSection;
  stationarity?: StationaritySection;
  rawStats?: JsonObject;
}
