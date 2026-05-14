export interface BriefIndex {
  dates: string[];
  updatedAt: string;
  latest?: BriefIndexRun | null;
  entriesByDate?: BriefIndexEntry[];
}

export interface BriefIndexRun {
  date: string;
  time: string;
  path: string;
  generatedAt: string;
  quality?: "ok" | "degraded" | "critical";
  headline?: string;
}

export interface BriefIndexEntry {
  date: string;
  runs: BriefIndexRun[];
}

export interface EtfHistoryPoint {
  date: string;
  totalBtc: number;
  totalAumUsd: number;
  deltaBtc: number | null;
}

export interface SovereignIndex {
  score: number;
  signalLabel: string;
  labelKo: string;
  zone: "bull" | "neutral" | "bear";
  qualityStatus: string;
  pcInterpretation?: string | null;
  todayScoreMethod?: string | null;
  trackAWfAvgHitRate?: number | null;
  trackAWfFolds?: number | null;
  /** 전일 대비 점수 변화 (양수=상승, 음수=하락) */
  scoreDelta?: number | null;
  /** 최근 30일 평균 점수 */
  score30dAvg?: number | null;
  /** 최근 30일 내 백분위 순위 (0~100) */
  scorePercentile?: number | null;
  /** 현재 riskOverlay 국면이 연속 유지된 일수 */
  regimeDurationDays?: number | null;
}

export interface BriefData {
  meta: BriefMeta;
  marketSnapshot: MarketSnapshot;
  riskOverlay: RiskOverlay | null;
  sovereignIndex: SovereignIndex | null;
  etfHistory: EtfHistoryPoint[] | null;
  aiJudgment: AIJudgment;
  topicSummaries: TopicSummary[];
  techStocks: TechStock[];
  cryptoIndicators: CryptoIndicator[];
  bitcoin: BitcoinSection;
  featuredXSignals: XSignal[] | null;
  allXSignals: XSignal[] | null;
  featuredNews: NewsItem[];
  allNews: NewsItem[];
}

export interface PublicNewsAnalysisAudit {
  candidateCount: number;
  requestedCount: number;
  successCount: number;
  failedCount: number;
  skippedCount: number;
  status: "ok" | "partial" | "failed" | "skipped";
}

export interface SentimentAggregate {
  mean: number | null;
  median: number | null;
  std: number | null;
  bullishRatio: number | null;
  bearishRatio: number | null;
  count: number;
}

export interface BriefMeta {
  date: string;
  generatedAt: string;
  dataQuality: "ok" | "degraded" | "critical";
  qualityNotes: string[];
  displayHeadline: string;
  sourceCounts: SourceCounts;
  translationStatus: "ok" | "partial" | "failed";
  publicNewsAnalysis: PublicNewsAnalysisAudit | null;
  sentimentStatus: "ok" | "skipped" | "failed";
  newsSentiment: SentimentAggregate | null;
  signalSentiment: SentimentAggregate | null;
  sentimentByCategory: Record<string, { mean: number; count: number }> | null;
}

export interface SourceCounts {
  newsCandidates: number;
  newsRanked: number;
  newsFeatured: number;
  newsAll: number;
  xSignalCandidates: number;
  xSignalRanked: number;
  xSignalFeatured: number;
  xSignalAll: number;
}

export interface MarketSnapshot {
  items: TickerItem[];
}

export interface TickerItem {
  symbol: string;
  label: string;
  value: string | null;
  change: string | null;
  trend: "up" | "down" | "neutral" | null;
  isCached: boolean;
  history: number[];
}

export interface CryptoIndicator extends TickerItem {
  description: string | null;
}

export interface RiskOverlay {
  regimeState: string;
  regimeDescription: string;
  volLevel: string;
  volTrend: string;
  volDescription: string;
  signalConfidence: string | null;
  signalReasons: string[];
  signalReasonLabels: string[];
  overlayGateDecision: string;
}

export interface AIJudgment {
  headline: string;
  body: string;
  summaryLead: string;
  summarySupport: string | null;
}

export interface TopicSummary {
  topic: "macro" | "bigtech" | "bitcoin" | "us-stocks";
  label: string;
  summary: string;
  rawSummary: string | null;
  keyMetric: string | null;
  relatedStocks: string[] | null;
}

export interface TechStock {
  symbol: string;
  name: string;
  price: string | null;
  change: string | null;
  trend: "up" | "down" | "neutral" | null;
  absChangeNum: number | null;
  isCached: boolean;
}

export interface FearGreedIndex {
  value: number;
  label: string;
}

export interface BTCEtfIssuer {
  name: string;
  holding: string | null;
  aum: string | null;
  sourceUrl: string;
}

export interface BTCEtfSection {
  totalHolding: string | null;
  totalAum: string | null;
  issuers: BTCEtfIssuer[];
}

export interface BitcoinSection {
  price: string | null;
  change: string | null;
  trend: "up" | "down" | "neutral" | null;
  fearGreedIndex: FearGreedIndex | null;
  etf: BTCEtfSection | null;
}

export interface XSignal {
  id: string;
  postedAt: string;
  impact: string;
  sentiment: "bullish" | "bearish" | "neutral";
  content: string;
  rawContent: string | null;
  sentimentScore: number | null;
  sentimentConfidence: number | null;
  sentimentLabel: "bullish" | "bearish" | "neutral" | null;
}

export interface NewsItem {
  id: string;
  publishedAt: string;
  category: "macro" | "bigtech" | "bitcoin" | "us-stocks";
  title: string;
  interpretation: string | null;
  summaryKo: string | null;
  rawTitle: string | null;
  rawSummary: string | null;
  rawInterpretation: string | null;
  source: string;
  sourceTier: "tier1" | "standard";
  url: string;
  urgency: "high" | "medium" | "low";
  tags: string[];
  sentimentScore: number | null;
  sentimentConfidence: number | null;
  sentimentLabel: "bullish" | "bearish" | "neutral" | null;
}
