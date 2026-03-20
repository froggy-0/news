import test from "node:test";
import assert from "node:assert/strict";

import { fetchBriefByDate, fetchIndex, fetchLatest } from "../lib/r2";

test("fetchLatest loads local fixture when R2 env is absent", async () => {
  const brief = await fetchLatest();
  assert.equal(brief.meta.date, "2026-03-21");
});

test("fetchIndex loads local fixture when R2 env is absent", async () => {
  const index = await fetchIndex();
  assert.deepEqual(index.dates.slice(0, 2), ["2026-03-21", "2026-03-20"]);
});

test("fetchBriefByDate loads dated fixture", async () => {
  const brief = await fetchBriefByDate("2026-03-20");
  assert.equal(brief.meta.dataQuality, "degraded");
});
