import test from "node:test";
import assert from "node:assert/strict";

import { loadBriefByDate, loadIndex, loadLatest } from "../lib/r2";

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
