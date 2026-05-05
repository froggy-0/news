import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { BitcoinPanel } from "../components/bitcoin/BitcoinPanel";
import { TerminalPanel } from "../components/hero/TerminalPanel";
import { NewsFeedList } from "../components/news/NewsFeedList";
import { DataState } from "../components/ui/DataState";
import { RevealSection } from "../components/ui/RevealSection";
import { SectionSkeleton } from "../components/ui/SectionSkeleton";

async function loadGlobalsCss() {
  return readFile(path.join(process.cwd(), "app", "globals.css"), "utf8");
}

test("globals.css defines required semantic tokens and removes scanline layer", async () => {
  const css = await loadGlobalsCss();

  assert.match(css, /--surface-canvas:/);
  assert.match(css, /--label-meta:/);
  assert.match(css, /--card-radius-reading:/);
  assert.match(css, /--card-padding-data:/);
  assert.match(css, /--type-body-mobile:\s*16px/);
  assert.match(css, /--type-meta-minimum:\s*12px/);
  assert.doesNotMatch(css, /\.scanline/);
});

test("state frame markup carries family and minHeight metadata", () => {
  const markup = renderToStaticMarkup(
    createElement(DataState, {
      title: "뉴스 상태",
      message: "이번 집계에서는 주요 뉴스를 확인하지 못했어요.",
      family: "reading",
      minHeight: 220,
    }),
  );

  assert.match(markup, /data-family="reading"/);
  assert.match(markup, /min-height:220px/);
  assert.match(markup, /뉴스 상태/);
});

test("state frame can represent partial and error tones for shared status UI", () => {
  const partialMarkup = renderToStaticMarkup(
    createElement(DataState, {
      title: "시장 지표 상태",
      message: "일부 데이터만 확인했어요.",
      tone: "partial",
      family: "data",
      minHeight: 160,
    }),
  );
  const errorMarkup = renderToStaticMarkup(
    createElement(DataState, {
      title: "뉴스 상태",
      message: "데이터를 불러오지 못했어요.",
      tone: "error",
      family: "reading",
      minHeight: 220,
    }),
  );

  assert.match(partialMarkup, /data-tone="partial"/);
  assert.match(errorMarkup, /data-tone="error"/);
});

test("loading tone uses shared section skeleton with reserved height", () => {
  const markup = renderToStaticMarkup(
    createElement(DataState, {
      title: "시장 지표 상태",
      message: "로딩 중",
      tone: "loading",
      family: "data",
      minHeight: 160,
    }),
  );

  assert.match(markup, /section-skeleton-data/);
  assert.match(markup, /min-height:160px/);
});

test("section skeleton reserves declared height for data boards", () => {
  const markup = renderToStaticMarkup(
    createElement(SectionSkeleton, {
      family: "data",
      lines: 3,
      minHeight: 160,
    }),
  );

  assert.match(markup, /min-height:160px/);
  assert.match(markup, /section-skeleton-data/);
});

test("reveal section exposes standardized scroll timing controls", () => {
  const markup = renderToStaticMarkup(
    createElement(
      RevealSection,
      {
        revealAt: 0.9,
        delayMs: 40,
        distancePx: 14,
        durationMs: 320,
      },
      "소스 피드",
    ),
  );

  assert.match(markup, /data-reveal-at="0.9"/);
  assert.match(markup, /data-delay-ms="40"/);
  assert.match(markup, /--reveal-distance:14px/);
  assert.match(markup, /--reveal-duration:320ms/);
});

test("reading, data, and utility card families are rendered by home components", () => {
  const readingMarkup = renderToStaticMarkup(
    createElement(NewsFeedList, {
      items: [
        {
          id: "news-1",
          url: "https://example.com/article",
          title: "금리와 달러 강세가 BTC 투자 심리에 주는 부담",
          rawTitle: null,
          summaryKo: "핵심 뉴스입니다. 시장 해석입니다.",
          interpretation: "장기 금리와 달러 흐름을 함께 읽어야 합니다.",
          source: "Reuters",
          sourceTier: "tier1",
          category: "macro",
          tags: ["rates"],
          publishedAt: "2026-03-21T00:00:00Z",
        },
      ] as any,
      emptyMessage: "empty",
    }),
  );
  const dataMarkup = renderToStaticMarkup(
    createElement(BitcoinPanel, {
      bitcoin: {
        price: "$71,282",
        change: "-0.16%",
        fearGreedIndex: { value: 58, label: "탐욕" },
        etf: null,
      } as any,
    }),
  );
  const utilityMarkup = renderToStaticMarkup(
    createElement(TerminalPanel, {
      meta: {
        date: "2026-03-21",
        generatedAt: "2026-03-21T08:01:00+09:00",
        dataQuality: "ok",
        translationStatus: "failed",
        sourceCounts: { newsCandidates: 0, xSignalCandidates: 0 },
      } as any,
      compact: true,
    }),
  );

  assert.match(readingMarkup, /card-family-reading/);
  assert.match(dataMarkup, /card-family-data/);
  assert.match(utilityMarkup, /card-family-utility/);
});
