import test from "node:test";
import assert from "node:assert/strict";

import { loadBriefByDate, loadIndex, loadLatest } from "../lib/r2";
import type { BriefData } from "@schema/brief.types";

test.afterEach(() => {
  delete process.env.BRIEF_DATA_SOURCE;
  delete process.env.NEXT_PUBLIC_R2_BASE_URL;
  delete process.env.R2_BASE_URL;
});

test("loadLatest requires explicit R2 base url when fixture mode is off", async () => {
  await assert.rejects(() => loadLatest(), /NEXT_PUBLIC_R2_BASE_URL is required/);
});

test("loadLatest loads local fixture only in explicit fixture mode", async () => {
  process.env.BRIEF_DATA_SOURCE = "fixture";
  const brief = await loadLatest();
  assert.equal(brief.meta.date, "2026-03-21");
});

test("loadIndex loads local fixture only in explicit fixture mode", async () => {
  process.env.BRIEF_DATA_SOURCE = "fixture";
  const index = await loadIndex();
  assert.deepEqual(index.dates.slice(0, 2), ["2026-03-21", "2026-03-20"]);
});

test("loadBriefByDate loads dated fixture in explicit fixture mode", async () => {
  process.env.BRIEF_DATA_SOURCE = "fixture";
  const brief = await loadBriefByDate("2026-03-20");
  assert.equal(brief.meta.dataQuality, "degraded");
});

test("loadLatest uses index.latest.path when expanded index is present", async () => {
  process.env.NEXT_PUBLIC_R2_BASE_URL = "https://example.com";

  const indexPayload = {
    dates: ["2026-03-21"],
    updatedAt: "2026-03-21T12:30:00Z",
    latest: {
      date: "2026-03-21",
      time: "1230",
      path: "curated/btc/2026-03-21.json",
      generatedAt: "2026-03-21T12:30:00Z",
    },
  };
  const briefPayload = {
    meta: {
      date: "2026-03-21",
      generatedAt: "2026-03-21T12:30:00Z",
      dataQuality: "ok",
      qualityNotes: [],
      displayHeadline: "",
      sourceCounts: {},
      translationStatus: "ok",
      sentimentStatus: "ok",
    },
    marketSnapshot: { items: [] },
    aiJudgment: { headline: "오늘은 관망 국면입니다.", body: "본문", summaryLead: "요약", summarySupport: null },
    topicSummaries: [],
    techStocks: [],
    bitcoin: { price: null, change: null, trend: null, fearGreedIndex: { value: 50, label: "Neutral" }, etf: null },
    featuredXSignals: null,
    allXSignals: null,
    featuredNews: [],
    allNews: [],
  } satisfies BriefData;

  const originalFetch = global.fetch;
  global.fetch = (async (input) => {
    const url = new URL(typeof input === "string" ? input : input.toString());
    if (url.pathname === "/index.json") {
      return new Response(JSON.stringify(indexPayload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.pathname === "/curated/btc/2026-03-21.json") {
      return new Response(JSON.stringify(briefPayload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.pathname === "/briefs/2026-03-21.json") {
      return new Response(null, { status: 404 });
    }
    return new Response(null, { status: 404 });
  }) as typeof fetch;

  try {
    const brief = await loadLatest();
    assert.equal(brief.aiJudgment.headline, "오늘은 관망 국면입니다.");
  } finally {
    global.fetch = originalFetch;
  }
});

test("loadLatest falls back to curated brief when index path points to analytics payload", async () => {
  process.env.NEXT_PUBLIC_R2_BASE_URL = "https://example.com";

  const originalFetch = global.fetch;
  const requestedPaths: string[] = [];
  global.fetch = (async (input) => {
    const url = new URL(typeof input === "string" ? input : input.toString());
    requestedPaths.push(url.pathname);

    if (url.pathname === "/index.json") {
      return new Response(
        JSON.stringify({
          dates: ["2026-03-21"],
          updatedAt: "2026-03-21T12:30:00Z",
          latest: {
            date: "2026-03-21",
            time: "1230",
            path: "analytics/btc/2026-03-21.json",
            generatedAt: "2026-03-21T12:30:00Z",
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.pathname === "/analytics/btc/2026-03-21.json") {
      return new Response(
        JSON.stringify({
          _backfill: true,
          symbol: "btc",
          date: "2026-03-21",
          newsSentiment: { mean: 0.2, std: 0.1, count: 3 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.pathname === "/curated/btc/2026-03-21.json") {
      return new Response(JSON.stringify(buildBriefPayload()), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(null, { status: 404 });
  }) as typeof fetch;

  try {
    const brief = await loadLatest();
    assert.equal(brief.aiJudgment.headline, "오늘은 관망 국면입니다.");
    assert.deepEqual(requestedPaths, [
      "/index.json",
      "/analytics/btc/2026-03-21.json",
      "/curated/btc/2026-03-21.json",
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

function buildBriefPayload(): BriefData {
  return {
    meta: {
      date: "2026-03-21",
      generatedAt: "2026-03-21T12:30:00Z",
      dataQuality: "ok",
      qualityNotes: [],
      displayHeadline: "",
      sourceCounts: {},
      translationStatus: "ok",
      sentimentStatus: "ok",
    },
    marketSnapshot: { items: [] },
    aiJudgment: { headline: "오늘은 관망 국면입니다.", body: "본문", summaryLead: "요약", summarySupport: null },
    topicSummaries: [],
    techStocks: [],
    bitcoin: { price: null, change: null, trend: null, fearGreedIndex: { value: 50, label: "Neutral" }, etf: null },
    featuredXSignals: null,
    allXSignals: null,
    featuredNews: [],
    allNews: [],
  };
}
