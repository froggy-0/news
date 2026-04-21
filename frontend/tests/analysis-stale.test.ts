import test from "node:test";
import assert from "node:assert/strict";

import { isStaleReferenceDate } from "../lib/analysis";

// KST = UTC+9, "today" 기준은 KST 자정으로 계산
// referenceDate: "2026-04-19", now: KST 기준 "2026-04-21 00:00:00" → diffDays=2 → stale

function kstDate(y: number, mo: number, d: number, h = 0, m = 0, s = 0): Date {
  // KST = UTC+9, KST 시각을 UTC Date로 변환
  return new Date(Date.UTC(y, mo - 1, d, h - 9, m, s));
}

test("1일 23h 59m 경과 → false", () => {
  // referenceDate = 2026-04-19, now = 2026-04-20 23:59 KST → diffDays=1
  const now = kstDate(2026, 4, 20, 23, 59, 0);
  assert.equal(isStaleReferenceDate("2026-04-19", now), false);
});

test("2일 0h 0m 경과 → true", () => {
  // referenceDate = 2026-04-19, now = 2026-04-21 00:00 KST → diffDays=2
  const now = kstDate(2026, 4, 21, 0, 0, 0);
  assert.equal(isStaleReferenceDate("2026-04-19", now), true);
});

test("2일 0h 1m 경과 → true", () => {
  const now = kstDate(2026, 4, 21, 0, 1, 0);
  assert.equal(isStaleReferenceDate("2026-04-19", now), true);
});

test("같은 날 → false", () => {
  const now = kstDate(2026, 4, 21, 12, 0, 0);
  assert.equal(isStaleReferenceDate("2026-04-21", now), false);
});

test("1일 경과 → false", () => {
  const now = kstDate(2026, 4, 21, 0, 0, 0);
  assert.equal(isStaleReferenceDate("2026-04-20", now), false);
});

test("3일 경과 → true", () => {
  const now = kstDate(2026, 4, 22, 10, 0, 0);
  assert.equal(isStaleReferenceDate("2026-04-19", now), true);
});
