export type GrangerDirection = "forward" | "reverse";

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

export interface GrangerSection {
  executed: boolean;
  correction: GrangerCorrection;
  results: GrangerResult[];
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

export interface SentimentInsightArtifact {
  generatedAtUtc: string;
  referenceDate: string;
  runId: string;
  granger: GrangerSection;
  pca: PcaSection;
}
