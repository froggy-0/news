import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { JudgmentBlock } from "../components/brief/JudgmentBlock";
import { TopicGrid } from "../components/brief/TopicGrid";
import { NewsFeed } from "../components/news/NewsFeed";
import { XSignals } from "../components/signals/XSignals";
import { buildHistoryEntries, buildMetaStatusCards } from "../lib/history";
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

test("meta status cards replace fake system metrics with operational labels", async () => {
  const brief = await loadBrief("2026-03-21.json");
  const cards = buildMetaStatusCards(brief.meta);

  assert.equal(cards[0]?.label, "Data Quality");
  assert.equal(cards[1]?.label, "Translation");
  assert.match(cards[2]?.value ?? "", /뉴스 0→0 · X 0→0/);
});

test("judgment block renders degraded quality notes in static markup", async () => {
  const brief = await loadBrief("degraded.json");
  const markup = renderToStaticMarkup(
    createElement(JudgmentBlock, {
      headline: brief.meta.displayHeadline || brief.aiJudgment.headline,
      summaryLead: brief.aiJudgment.summaryLead,
      summarySupport: brief.aiJudgment.summarySupport,
      issueDate: brief.meta.date,
      generatedAt: brief.meta.generatedAt,
      variant: "home",
    }),
  );

  assert.match(markup, /핵심 인사이트/);
  assert.doesNotMatch(markup, /신뢰 상태|발행 기준일|생성 시각/);
});

test("topic grid returns null when topic summaries are absent", () => {
  const element = TopicGrid({ items: [], variant: "home" });
  assert.equal(element, null);
});

test("news feed detail renders all news cards from fixture", async () => {
  const brief = await loadBrief("2026-03-20.json");
  const markup = renderToStaticMarkup(
    createElement(NewsFeed, {
      featuredItems: brief.featuredNews,
      allItems: brief.allNews,
      variant: "detail",
      showRawTitle: true,
    }),
  );

  assert.match(markup, /전체 뉴스 플로우/);
  assert.match(markup, /Full Source Flow/);
});

test("news feed returns null when both featured and all news are absent", () => {
  const element = NewsFeed({
    featuredItems: [],
    allItems: [],
    variant: "home",
  });

  assert.equal(element, null);
});

test("x signals component returns null when both featured and all signals are absent", () => {
  const element = XSignals({
    featuredItems: null,
    allItems: null,
    variant: "detail",
  });

  assert.equal(element, null);
});
