import type {
  AIJudgment,
  BitcoinSection,
  BriefData,
  BriefIndex,
  BriefMeta,
  FearGreedIndex,
  MarketSnapshot,
  NewsItem,
  TechStock,
  TickerItem,
  TopicSummary,
  XSignal,
} from "@schema/brief.types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} must be a non-empty string`);
  }
  return value;
}

function asOptionalString(value: unknown, name: string): string | null {
  if (value === null) {
    return null;
  }
  return asString(value, name);
}

function asStringArray(value: unknown, name: string): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error(`${name} must be a string array`);
  }
  return value;
}

function asNumberArray(value: unknown, name: string): number[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "number")) {
    throw new Error(`${name} must be a number array`);
  }
  return value;
}

function asQuality(value: unknown): BriefMeta["dataQuality"] {
  if (value === "ok" || value === "degraded" || value === "critical") {
    return value;
  }
  throw new Error("meta.dataQuality must be ok, degraded, or critical");
}

function asTrend(value: unknown): TickerItem["trend"] {
  if (value === "up" || value === "down" || value === "neutral" || value === null) {
    return value;
  }
  throw new Error("trend must be up, down, neutral, or null");
}

function parseMeta(value: unknown): BriefMeta {
  if (!isRecord(value)) {
    throw new Error("meta must be an object");
  }
  return {
    date: asString(value.date, "meta.date"),
    generatedAt: asString(value.generatedAt, "meta.generatedAt"),
    dataQuality: asQuality(value.dataQuality),
    qualityNotes: asStringArray(value.qualityNotes, "meta.qualityNotes"),
  };
}

function parseTickerItem(value: unknown): TickerItem {
  if (!isRecord(value)) {
    throw new Error("ticker item must be an object");
  }
  const history = value.history === undefined ? [] : asNumberArray(value.history, "tickerItem.history");
  return {
    symbol: asString(value.symbol, "tickerItem.symbol"),
    label: asString(value.label, "tickerItem.label"),
    value: asOptionalString(value.value, "tickerItem.value"),
    change: asOptionalString(value.change, "tickerItem.change"),
    trend: asTrend(value.trend),
    isCached: Boolean(value.isCached),
    history,
  };
}

function parseMarketSnapshot(value: unknown): MarketSnapshot {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new Error("marketSnapshot.items must be an array");
  }
  return {
    items: value.items.map(parseTickerItem),
  };
}

function parseAIJudgment(value: unknown): AIJudgment {
  if (!isRecord(value)) {
    throw new Error("aiJudgment must be an object");
  }
  return {
    headline: asString(value.headline, "aiJudgment.headline"),
    body: asString(value.body, "aiJudgment.body"),
  };
}

function parseTopicSummary(value: unknown): TopicSummary {
  if (!isRecord(value)) {
    throw new Error("topic summary must be an object");
  }
  const topic = value.topic;
  if (topic !== "macro" && topic !== "bigtech" && topic !== "bitcoin" && topic !== "us-stocks") {
    throw new Error("topicSummaries.topic must be a known topic");
  }
  return {
    topic,
    label: asString(value.label, "topicSummary.label"),
    summary: asString(value.summary, "topicSummary.summary"),
    keyMetric: asOptionalString(value.keyMetric, "topicSummary.keyMetric"),
    relatedStocks:
      value.relatedStocks === null
        ? null
        : asStringArray(value.relatedStocks, "topicSummary.relatedStocks"),
  };
}

function parseTechStock(value: unknown): TechStock {
  if (!isRecord(value)) {
    throw new Error("tech stock must be an object");
  }
  const absChangeNum = value.absChangeNum;
  if (absChangeNum !== null && absChangeNum !== undefined && typeof absChangeNum !== "number") {
    throw new Error("techStock.absChangeNum must be a number or null");
  }
  return {
    symbol: asString(value.symbol, "techStock.symbol"),
    name: asString(value.name, "techStock.name"),
    price: asOptionalString(value.price, "techStock.price"),
    change: asOptionalString(value.change, "techStock.change"),
    trend: asTrend(value.trend),
    absChangeNum: absChangeNum ?? null,
    isCached: Boolean(value.isCached),
  };
}

function parseFearGreed(value: unknown): FearGreedIndex {
  if (!isRecord(value) || typeof value.value !== "number") {
    throw new Error("fearGreedIndex must be an object with numeric value");
  }
  return {
    value: value.value,
    label: asString(value.label, "bitcoin.fearGreedIndex.label"),
  };
}

function parseBitcoin(value: unknown): BitcoinSection {
  if (!isRecord(value)) {
    throw new Error("bitcoin must be an object");
  }
  const etfValue = value.etf;
  let etf: BitcoinSection["etf"] = null;
  if (etfValue !== null) {
    if (!isRecord(etfValue) || !Array.isArray(etfValue.issuers)) {
      throw new Error("bitcoin.etf must be null or an object with issuers");
    }
    etf = {
      totalHolding: asOptionalString(etfValue.totalHolding, "bitcoin.etf.totalHolding"),
      totalAum: asOptionalString(etfValue.totalAum, "bitcoin.etf.totalAum"),
      issuers: etfValue.issuers.map((issuer) => {
        if (!isRecord(issuer)) {
          throw new Error("bitcoin.etf.issuers item must be an object");
        }
        return {
          name: asString(issuer.name, "bitcoin.etf.issuer.name"),
          holding: asOptionalString(issuer.holding, "bitcoin.etf.issuer.holding"),
          aum: asOptionalString(issuer.aum, "bitcoin.etf.issuer.aum"),
          sourceUrl: asString(issuer.sourceUrl, "bitcoin.etf.issuer.sourceUrl"),
        };
      }),
    };
  }
  return {
    price: asOptionalString(value.price, "bitcoin.price"),
    change: asOptionalString(value.change, "bitcoin.change"),
    trend: asTrend(value.trend),
    fearGreedIndex: value.fearGreedIndex === null ? null : parseFearGreed(value.fearGreedIndex),
    etf,
  };
}

function parseSignal(value: unknown): XSignal {
  if (!isRecord(value)) {
    throw new Error("xSignal must be an object");
  }
  const sentiment = value.sentiment;
  if (sentiment !== "bullish" && sentiment !== "bearish" && sentiment !== "neutral") {
    throw new Error("xSignal.sentiment must be bullish, bearish, or neutral");
  }
  return {
    id: asString(value.id, "xSignal.id"),
    postedAt: asString(value.postedAt, "xSignal.postedAt"),
    impact: asString(value.impact, "xSignal.impact"),
    sentiment,
    content: asString(value.content, "xSignal.content"),
  };
}

function parseNewsItem(value: unknown): NewsItem {
  if (!isRecord(value)) {
    throw new Error("news item must be an object");
  }
  const category = value.category;
  if (category !== "macro" && category !== "bigtech" && category !== "bitcoin" && category !== "us-stocks") {
    throw new Error("news.category must be a known category");
  }
  const sourceTier = value.sourceTier;
  if (sourceTier !== "tier1" && sourceTier !== "standard") {
    throw new Error("news.sourceTier must be tier1 or standard");
  }
  const urgency = value.urgency;
  if (urgency !== "high" && urgency !== "medium" && urgency !== "low") {
    throw new Error("news.urgency must be high, medium, or low");
  }
  return {
    id: asString(value.id, "news.id"),
    publishedAt: asString(value.publishedAt, "news.publishedAt"),
    category,
    title: asString(value.title, "news.title"),
    interpretation: asOptionalString(value.interpretation, "news.interpretation"),
    source: asString(value.source, "news.source"),
    sourceTier,
    url: asString(value.url, "news.url"),
    urgency,
    tags: asStringArray(value.tags, "news.tags"),
  };
}

export function parseBriefIndex(value: unknown): BriefIndex {
  if (!isRecord(value)) {
    throw new Error("index payload must be an object");
  }
  return {
    dates: asStringArray(value.dates, "index.dates"),
    updatedAt: asString(value.updatedAt, "index.updatedAt"),
  };
}

export function parseBriefData(value: unknown): BriefData {
  if (!isRecord(value)) {
    throw new Error("brief payload must be an object");
  }
  const xSignalsValue = value.xSignals;
  if (xSignalsValue !== null && !Array.isArray(xSignalsValue)) {
    throw new Error("xSignals must be null or an array");
  }
  if (!Array.isArray(value.topicSummaries) || !Array.isArray(value.techStocks) || !Array.isArray(value.news)) {
    throw new Error("topicSummaries, techStocks, and news must be arrays");
  }
  return {
    meta: parseMeta(value.meta),
    marketSnapshot: parseMarketSnapshot(value.marketSnapshot),
    aiJudgment: parseAIJudgment(value.aiJudgment),
    topicSummaries: value.topicSummaries.map(parseTopicSummary),
    techStocks: value.techStocks.map(parseTechStock),
    bitcoin: parseBitcoin(value.bitcoin),
    xSignals: xSignalsValue === null ? null : xSignalsValue.map(parseSignal),
    news: value.news.map(parseNewsItem),
  };
}
