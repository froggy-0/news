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
  xSignals: XSignal[] | null;
  news: NewsItem[];
}

export interface BriefMeta {
  date: string;
  generatedAt: string;
  dataQuality: "ok" | "degraded" | "critical";
  qualityNotes: string[];
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
}

export interface NewsItem {
  id: string;
  publishedAt: string;
  category: "macro" | "bigtech" | "bitcoin" | "us-stocks";
  title: string;
  interpretation: string | null;
  source: string;
  sourceTier: "tier1" | "standard";
  url: string;
  urgency: "high" | "medium" | "low";
  tags: string[];
}
