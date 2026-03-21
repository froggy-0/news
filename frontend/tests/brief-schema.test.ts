import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { parseBriefData, parseBriefIndex } from "../lib/brief-schema";

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
  assert.ok(brief.news.length > 0);
});

test("degraded fixture preserves quality notes", async () => {
  const brief = parseBriefData(await loadJson("degraded.json"));
  assert.equal(brief.meta.dataQuality, "degraded");
  assert.ok(brief.meta.qualityNotes.length > 0);
});
