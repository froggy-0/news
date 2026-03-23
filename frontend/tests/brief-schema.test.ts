import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { parseBriefData, parseBriefIndex } from "../lib/brief-schema";
import { hasUsableHeadline } from "../lib/format";

async function loadJson(name: string): Promise<unknown> {
  const fullPath = path.join(process.cwd(), "fixtures", name);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw) as unknown;
}

test("index fixture matches contract", async () => {
  const index = parseBriefIndex(await loadJson("index.json"));
  assert.equal(index.dates.length, 3);
});

test("dated brief fixture matches contract", async () => {
  const brief = parseBriefData(await loadJson("2026-03-20.json"));
  assert.equal(brief.meta.dataQuality, "degraded");
  assert.ok(brief.marketSnapshot.items.length > 0);
  assert.ok(brief.featuredNews.length > 0);
  assert.ok(brief.allNews.length > 0);
});

test("degraded fixture preserves quality notes", async () => {
  const brief = parseBriefData(await loadJson("degraded.json"));
  assert.equal(brief.meta.dataQuality, "degraded");
  assert.ok(brief.meta.qualityNotes.length > 0);
});

test("display headline helper rejects source labels and urls", () => {
  assert.equal(hasUsableHeadline("참고 출처"), false);
  assert.equal(hasUsableHeadline("발행본"), false);
  assert.equal(hasUsableHeadline("https://www.reuters.com/world/us/fed-keeps-options-open"), false);
  assert.equal(hasUsableHeadline("오늘은 관망 국면입니다."), true);
});
