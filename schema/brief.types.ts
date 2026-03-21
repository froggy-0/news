export interface BriefIndex {
  dates: string[];
  updatedAt: string;
}

export interface BriefData {
  meta: BriefMeta;
  marketSnapshot: MarketSnapshot;
  aiJudgment: AIJudgment;
  topicSummaries: TopicSummary[];
  techStocks: TechStock[];
  bitcoin: BitcoinSection;
  featuredXSignals: XSignal[] | null;
  allXSignals: XSignal[] | null;
  featuredNews: NewsItem[];
  allNews: NewsItem[];
}

export interface BriefMeta {
  date: string;
  generatedAt: string;
  dataQuality: "ok" | "degraded" | "critical";
  qualityNotes: string[];
  displayHeadline: string;
  sourceCounts: SourceCounts;
  translationStatus: "ok" | "partial" | "failed";
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
}

export interface NewsItem {
  id: string;
  publishedAt: string;
  category: "macro" | "bigtech" | "bitcoin" | "us-stocks";
  title: string;
  interpretation: string | null;
  summaryKo: string | null;
  rawTitle: string | null;
  source: string;
  sourceTier: "tier1" | "standard";
  url: string;
  urgency: "high" | "medium" | "low";
  tags: string[];
}
