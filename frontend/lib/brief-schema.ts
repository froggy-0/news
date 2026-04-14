import type {
  AIJudgment,
  BitcoinSection,
  BriefData,
  BriefIndexEntry,
  BriefIndex,
  BriefIndexRun,
  BriefMeta,
  FearGreedIndex,
  MarketSnapshot,
  NewsItem,
  PublicNewsAnalysisAudit,
  SentimentAggregate,
  SourceCounts,
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

function asOptionalQuality(value: unknown): BriefMeta["dataQuality"] | undefined {
  if (value === undefined) {
    return undefined;
  }
  return asQuality(value);
}

function asTrend(value: unknown): TickerItem["trend"] {
  if (value === "up" || value === "down" || value === "neutral" || value === null) {
    return value;
  }
  throw new Error("trend must be up, down, neutral, or null");
}

function asTranslationStatus(value: unknown): BriefMeta["translationStatus"] {
  if (value === "ok" || value === "partial" || value === "failed") {
    return value;
  }
  return "failed";
}

function parseSourceCounts(value: unknown): SourceCounts {
  if (!isRecord(value)) {
    return {
      newsCandidates: 0,
      newsRanked: 0,
      newsFeatured: 0,
      newsAll: 0,
      xSignalCandidates: 0,
      xSignalRanked: 0,
      xSignalFeatured: 0,
      xSignalAll: 0,
    };
  }
  const asCount = (item: unknown) => (typeof item === "number" && item >= 0 ? item : 0);
  return {
    newsCandidates: asCount(value.newsCandidates),
    newsRanked: asCount(value.newsRanked),
    newsFeatured: asCount(value.newsFeatured),
    newsAll: asCount(value.newsAll),
    xSignalCandidates: asCount(value.xSignalCandidates),
    xSignalRanked: asCount(value.xSignalRanked),
    xSignalFeatured: asCount(value.xSignalFeatured),
    xSignalAll: asCount(value.xSignalAll),
  };
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
    displayHeadline:
      typeof value.displayHeadline === "string" && value.displayHeadline.length > 0
        ? value.displayHeadline
        : "",
    sourceCounts: parseSourceCounts(value.sourceCounts),
    translationStatus: asTranslationStatus(value.translationStatus),
    publicNewsAnalysis: isRecord(value.publicNewsAnalysis)
      ? {
          candidateCount: typeof value.publicNewsAnalysis.candidateCount === "number" ? value.publicNewsAnalysis.candidateCount : 0,
          requestedCount: typeof value.publicNewsAnalysis.requestedCount === "number" ? value.publicNewsAnalysis.requestedCount : 0,
          successCount: typeof value.publicNewsAnalysis.successCount === "number" ? value.publicNewsAnalysis.successCount : 0,
          failedCount: typeof value.publicNewsAnalysis.failedCount === "number" ? value.publicNewsAnalysis.failedCount : 0,
          skippedCount: typeof value.publicNewsAnalysis.skippedCount === "number" ? value.publicNewsAnalysis.skippedCount : 0,
          status: (["ok", "partial", "failed", "skipped"].includes(value.publicNewsAnalysis.status as string)
            ? value.publicNewsAnalysis.status
            : "skipped") as PublicNewsAnalysisAudit["status"],
        }
      : null,
    sentimentStatus: (["ok", "skipped", "failed"].includes(value.sentimentStatus as string)
      ? value.sentimentStatus
      : "skipped") as BriefMeta["sentimentStatus"],
    newsSentiment: isRecord(value.newsSentiment) ? parseSentimentAggregate(value.newsSentiment) : null,
    signalSentiment: isRecord(value.signalSentiment) ? parseSentimentAggregate(value.signalSentiment) : null,
    sentimentByCategory: isRecord(value.sentimentByCategory) ? (value.sentimentByCategory as BriefMeta["sentimentByCategory"]) : null,
  };
}

function parseSentimentAggregate(value: Record<string, unknown>): SentimentAggregate {
  return {
    mean: typeof value.mean === "number" ? value.mean : null,
    median: typeof value.median === "number" ? value.median : null,
    std: typeof value.std === "number" ? value.std : null,
    bullishRatio: typeof value.bullishRatio === "number" ? value.bullishRatio : null,
    bearishRatio: typeof value.bearishRatio === "number" ? value.bearishRatio : null,
    count: typeof value.count === "number" ? value.count : 0,
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
  const body = asString(value.body, "aiJudgment.body");
  const summaryLead =
    typeof value.summaryLead === "string" && value.summaryLead.length > 0
      ? value.summaryLead
      : body
          .split("\n")
          .map((line) => line.trim())
          .find((line) => line.length > 0 && !line.startsWith("##"))
        ?? "";
  return {
    headline: asString(value.headline, "aiJudgment.headline"),
    body,
    summaryLead,
    summarySupport:
      value.summarySupport === undefined
        ? null
        : asOptionalString(value.summarySupport, "aiJudgment.summarySupport"),
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
    rawSummary: value.rawSummary === undefined ? null : asOptionalString(value.rawSummary, "topicSummary.rawSummary"),
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
    rawContent:
      value.rawContent === undefined ? null : asOptionalString(value.rawContent, "xSignal.rawContent"),
    sentimentScore: typeof value.sentimentScore === "number" ? value.sentimentScore : null,
    sentimentConfidence: typeof value.sentimentConfidence === "number" ? value.sentimentConfidence : null,
    sentimentLabel: (["bullish", "bearish", "neutral"].includes(value.sentimentLabel as string)
      ? value.sentimentLabel
      : null) as XSignal["sentimentLabel"],
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
    summaryKo: value.summaryKo === undefined ? null : asOptionalString(value.summaryKo, "news.summaryKo"),
    rawTitle: value.rawTitle === undefined ? null : asOptionalString(value.rawTitle, "news.rawTitle"),
    rawSummary: value.rawSummary === undefined ? null : asOptionalString(value.rawSummary, "news.rawSummary"),
    rawInterpretation: value.rawInterpretation === undefined ? null : asOptionalString(value.rawInterpretation, "news.rawInterpretation"),
    source: asString(value.source, "news.source"),
    sourceTier,
    url: asString(value.url, "news.url"),
    urgency,
    tags: asStringArray(value.tags, "news.tags"),
    sentimentScore: typeof value.sentimentScore === "number" ? value.sentimentScore : null,
    sentimentConfidence: typeof value.sentimentConfidence === "number" ? value.sentimentConfidence : null,
    sentimentLabel: (["bullish", "bearish", "neutral"].includes(value.sentimentLabel as string)
      ? value.sentimentLabel
      : null) as NewsItem["sentimentLabel"],
  };
}

export function parseBriefIndex(value: unknown): BriefIndex {
  if (!isRecord(value)) {
    throw new Error("index payload must be an object");
  }

  const parseIndexRun = (run: unknown, name: string): BriefIndexRun => {
    if (!isRecord(run)) {
      throw new Error(`${name} must be an object`);
    }

    return {
      date: asString(run.date, `${name}.date`),
      time: asString(run.time, `${name}.time`),
      path: asString(run.path, `${name}.path`),
      generatedAt: asString(run.generatedAt, `${name}.generatedAt`),
      quality: asOptionalQuality(run.quality),
      headline:
        typeof run.headline === "string" && run.headline.length > 0
          ? run.headline
          : undefined,
    };
  };

  const parseIndexEntry = (entry: unknown, index: number): BriefIndexEntry => {
    if (!isRecord(entry)) {
      throw new Error(`index.entriesByDate[${index}] must be an object`);
    }
    if (!Array.isArray(entry.runs)) {
      throw new Error(`index.entriesByDate[${index}].runs must be an array`);
    }
    return {
      date: asString(entry.date, `index.entriesByDate[${index}].date`),
      runs: entry.runs.map((run, runIndex) => parseIndexRun(run, `index.entriesByDate[${index}].runs[${runIndex}]`)),
    };
  };

  return {
    dates: asStringArray(value.dates, "index.dates"),
    updatedAt: asString(value.updatedAt, "index.updatedAt"),
    latest: value.latest === undefined ? null : parseIndexRun(value.latest, "index.latest"),
    entriesByDate:
      value.entriesByDate === undefined
        ? []
        : Array.isArray(value.entriesByDate)
          ? value.entriesByDate.map(parseIndexEntry)
          : (() => {
              throw new Error("index.entriesByDate must be an array");
            })(),
  };
}

export function parseBriefData(value: unknown): BriefData {
  if (!isRecord(value)) {
    throw new Error("brief payload must be an object");
  }
  const featuredXSignalsValue =
    Array.isArray(value.featuredXSignals) || value.featuredXSignals === null
      ? value.featuredXSignals
      : value.xSignals;
  const allXSignalsValue =
    Array.isArray(value.allXSignals) || value.allXSignals === null ? value.allXSignals : value.xSignals;
  if (
    featuredXSignalsValue !== null &&
    featuredXSignalsValue !== undefined &&
    !Array.isArray(featuredXSignalsValue)
  ) {
    throw new Error("featuredXSignals must be null or an array");
  }
  if (allXSignalsValue !== null && allXSignalsValue !== undefined && !Array.isArray(allXSignalsValue)) {
    throw new Error("allXSignals must be null or an array");
  }
  const featuredNewsValue = Array.isArray(value.featuredNews) ? value.featuredNews : value.news;
  const allNewsValue = Array.isArray(value.allNews) ? value.allNews : value.news;
  if (
    !Array.isArray(value.topicSummaries) ||
    !Array.isArray(value.techStocks) ||
    !Array.isArray(featuredNewsValue) ||
    !Array.isArray(allNewsValue)
  ) {
    throw new Error("topicSummaries, techStocks, featuredNews, and allNews must be arrays");
  }
  return {
    meta: parseMeta(value.meta),
    marketSnapshot: parseMarketSnapshot(value.marketSnapshot),
    aiJudgment: parseAIJudgment(value.aiJudgment),
    topicSummaries: value.topicSummaries.map(parseTopicSummary),
    techStocks: value.techStocks.map(parseTechStock),
    bitcoin: parseBitcoin(value.bitcoin),
    featuredXSignals:
      featuredXSignalsValue === null || featuredXSignalsValue === undefined
        ? null
        : featuredXSignalsValue.map(parseSignal),
    allXSignals:
      allXSignalsValue === null || allXSignalsValue === undefined ? null : allXSignalsValue.map(parseSignal),
    featuredNews: featuredNewsValue.map(parseNewsItem),
    allNews: allNewsValue.map(parseNewsItem),
  };
}
