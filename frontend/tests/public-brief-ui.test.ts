import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { EtfInflowChart } from "../components/bitcoin/EtfInflowChart";
import { BriefBody } from "../components/brief/BriefBody";
import { JudgmentBlock } from "../components/brief/JudgmentBlock";
import { RiskOverlayPanel } from "../components/brief/RiskOverlayPanel";
import { TopicGrid } from "../components/brief/TopicGrid";
import { HomeHero } from "../components/hero/HomeHero";
import { NewsFeed } from "../components/news/NewsFeed";
import { XSignals } from "../components/signals/XSignals";
import { buildHistoryEntries } from "../lib/history";
import { parseBriefData } from "../lib/brief-schema";

async function loadBrief(name: string) {
  const fullPath = path.join(process.cwd(), "fixtures", name);
  const raw = await readFile(fullPath, "utf8");
  return parseBriefData(JSON.parse(raw) as unknown);
}

test("history entries preserve archive hrefs and current date", () => {
  const entries = buildHistoryEntries(["2026-03-21", "2026-03-20"], "2026-03-20");
  assert.deepEqual(entries, [
    { date: "2026-03-21", href: "/archive/2026-03-21", isCurrent: false },
    { date: "2026-03-20", href: "/archive/2026-03-20", isCurrent: true },
  ]);
});

test("judgment block renders headline in static markup", async () => {
  const brief = await loadBrief("degraded.json");
  const markup = renderToStaticMarkup(
    createElement(JudgmentBlock, {
      headline: brief.meta.displayHeadline || brief.aiJudgment.headline,
      summaryLead: brief.aiJudgment.summaryLead,
      summarySupport: brief.aiJudgment.summarySupport,
      issueDate: brief.meta.date,
    }),
  );

  assert.match(markup, /핵심 인사이트/);
  assert.doesNotMatch(markup, /신뢰 상태|발행 기준일|생성 시각/);
});

test("risk overlay panel renders market state cards", async () => {
  const brief = await loadBrief("2026-03-21.json");
  const markup = renderToStaticMarkup(createElement(RiskOverlayPanel, { overlay: brief.riskOverlay }));

  assert.match(markup, /시장 상태/);
  assert.match(markup, /방향 불명/);
  assert.match(markup, /변동성/);
  assert.match(markup, /오늘의 신호/);
  assert.match(markup, /검증 기준 통과/);
});

test("etf inflow chart renders range controls and summary cards", () => {
  const history = Array.from({ length: 16 }, (_, index) => {
    const day = String(index + 1).padStart(2, "0");
    return {
      date: `2026-03-${day}`,
      totalBtc: 980_000 + index * 720,
      totalAumUsd: 98_000_000_000 + index * 125_000_000,
      deltaBtc: index === 0 ? null : index % 3 === 0 ? -420 : 760,
    };
  });
  const markup = renderToStaticMarkup(createElement(EtfInflowChart, { history }));

  assert.match(markup, /7D/);
  assert.match(markup, /14D/);
  assert.match(markup, /30D/);
  assert.match(markup, /ALL/);
  assert.match(markup, /오늘 순유입/);
  assert.match(markup, /선택 기간 순유입/);
  assert.match(markup, /총 보유 BTC/);
  assert.match(markup, /총 AUM/);
});

test("brief body hides wrapper copy, download button, and data quality line", () => {
  const markup = renderToStaticMarkup(
    createElement(BriefBody, {
      body: "## 오늘의 판단\n\nBTC ETF 유입이 이어졌습니다.\n\n데이터 품질 상태: ok",
      date: "2026-03-21",
    }),
  );

  assert.match(markup, /BTC ETF 유입이 이어졌습니다/);
  assert.doesNotMatch(markup, /전체 브리핑/);
  assert.doesNotMatch(markup, /Download MD/);
  assert.doesNotMatch(markup, /데이터 품질 상태:/);
});

test("topic grid renders empty state when topic summaries are absent", () => {
  const markup = renderToStaticMarkup(createElement(TopicGrid, { items: [] }));
  assert.match(markup, /테마 상태/);
  assert.match(markup, /유효한 주요 테마 요약을 확인하지 못했어요/);
});

test("home hero renders brief entry CTA and deterministic seed marker", async () => {
  const brief = await loadBrief("2026-03-21.json");
  const markup = renderToStaticMarkup(
    createElement(HomeHero, {
      brief,
      heroSeed: brief.meta.date,
      latestDate: brief.meta.date,
    }),
  );

  assert.match(markup, /data-hero-seed="2026-03-21"/);
  assert.match(markup, /오늘 브리프 먼저 읽기/);
});

test("news feed detail renders all news cards from fixture", async () => {
  const brief = await loadBrief("2026-03-20.json");
  const markup = renderToStaticMarkup(
    createElement(NewsFeed, {
      featuredItems: brief.featuredNews,
      allItems: brief.allNews,
      showRawTitle: true,
    }),
  );

  assert.match(markup, /전체 뉴스 플로우/);
  assert.match(markup, /Full Source Flow/);
});

test("news feed renders nothing when both featured and all news are absent", () => {
  const markup = renderToStaticMarkup(
    createElement(NewsFeed, {
      featuredItems: [],
      allItems: [],
    }),
  );

  assert.strictEqual(markup, "");
});

test("x signals component renders empty state when both featured and all signals are absent", () => {
  const markup = renderToStaticMarkup(
    createElement(XSignals, {
      featuredItems: null,
      allItems: null,
    }),
  );

  assert.match(markup, /X 시그널 상태/);
  assert.match(markup, /전체 X 시그널을 확인하지 못했어요/);
});
