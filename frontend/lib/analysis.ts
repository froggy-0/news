import path from "node:path";
import { readFile } from "node:fs/promises";

import type { SentimentInsightArtifact } from "@schema/analysis.types";

import { parseSentimentInsight } from "./analysis-schema";
import { resolvePublicR2BaseUrl, requireAbsoluteHttpUrl, PUBLIC_R2_BASE_URL_ENV } from "./public-r2-env";

const ANALYSIS_R2_PATH = "analytics/sentiment/latest.json";
const FIXTURE_NAME = "sentiment-insight.json";

function useFixtureData(): boolean {
  return process.env.BRIEF_DATA_SOURCE === "fixture";
}

async function readFixture(): Promise<unknown> {
  const fullPath = path.join(process.cwd(), "fixtures", FIXTURE_NAME);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw);
}

export async function fetchSentimentInsight(): Promise<SentimentInsightArtifact> {
  if (useFixtureData()) {
    return parseSentimentInsight(await readFixture());
  }

  const baseUrl = resolvePublicR2BaseUrl();
  if (!baseUrl) {
    throw new Error(
      `${PUBLIC_R2_BASE_URL_ENV} is required for fetching sentiment insight data.`,
    );
  }

  const url = `${requireAbsoluteHttpUrl(baseUrl, PUBLIC_R2_BASE_URL_ENV)}/${ANALYSIS_R2_PATH}`;
  const cacheMode: RequestCache = process.env.NODE_ENV === "development" ? "no-store" : "force-cache";
  const response = await fetch(url, { cache: cacheMode });
  if (!response.ok) {
    throw new Error(`Failed to fetch sentiment insight: ${response.status} ${url}`);
  }

  return parseSentimentInsight(await response.json());
}

/**
 * KST 기준으로 referenceDate가 현재 시각보다 2일 이상 경과했으면 true.
 * referenceDate: "YYYY-MM-DD"
 * now: Date (기본 현재 시각)
 */
export function isStaleReferenceDate(referenceDate: string, now: Date = new Date()): boolean {
  // KST = UTC+9
  const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
  const nowKst = new Date(now.getTime() + KST_OFFSET_MS);
  // KST 자정 기준 날짜 문자열
  const todayKst = nowKst.toISOString().slice(0, 10);

  const refMs = new Date(`${referenceDate}T00:00:00Z`).getTime();
  const todayMs = new Date(`${todayKst}T00:00:00Z`).getTime();

  const diffDays = (todayMs - refMs) / (24 * 60 * 60 * 1000);
  return diffDays >= 2;
}
