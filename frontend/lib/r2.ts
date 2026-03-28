import { cache } from "react";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import type { BriefData, BriefIndex } from "@schema/brief.types";

import { parseBriefData, parseBriefIndex } from "./brief-schema";

const fixtureDir = path.join(process.cwd(), "fixtures");
const outputDir = path.resolve(process.cwd(), "..", "output");
const requestVersion =
  process.env.BRIEF_DATA_BUILD_ID ??
  process.env.GITHUB_SHA ??
  process.env.VERCEL_GIT_COMMIT_SHA ??
  `local-${Date.now()}`;
const outputBriefPattern = /^briefs_(\d{4}-\d{2}-\d{2})\.json$/;

export type ArchiveBriefSummary = {
  date: string;
  generatedAt?: string;
  quality?: "ok" | "degraded" | "critical";
  headline?: string;
  displayHeadline?: string;
  translationStatus?: "ok" | "partial" | "failed";
  newsAll?: number;
  xSignalAll?: number;
};

async function readFixture<T>(name: string): Promise<T> {
  const fullPath = path.join(fixtureDir, name);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw) as T;
}

async function readOutputBrief<T>(date: string): Promise<T> {
  const fullPath = path.join(outputDir, `briefs_${date}.json`);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw) as T;
}

async function readOutputIndex(): Promise<BriefIndex> {
  const entries = await readdir(outputDir, { withFileTypes: true });
  const candidates = entries
    .filter((entry) => entry.isFile())
    .map((entry) => outputBriefPattern.exec(entry.name)?.[1] ?? null)
    .filter((date): date is string => date !== null);
  const validated = await Promise.all(
    candidates.map(async (date) => {
      try {
        await readOutputBrief<unknown>(date);
        return date;
      } catch {
        return null;
      }
    }),
  );
  const dates = validated
    .filter((date): date is string => date !== null)
    .sort((left, right) => right.localeCompare(left));

  return {
    dates,
    updatedAt: new Date().toISOString(),
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  const requestUrl = new URL(url);
  requestUrl.searchParams.set("_build", requestVersion);

  const response = await fetch(requestUrl, {
    cache: "force-cache",
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch ${requestUrl}: ${response.status}`);
  }

  return (await response.json()) as T;
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function asOptionalRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function parseArchiveSummary(value: unknown, expectedDate?: string): ArchiveBriefSummary {
  const root = asRecord(value, "brief");
  const meta = asRecord(root.meta, "brief.meta");
  const aiJudgment = asRecord(root.aiJudgment, "brief.aiJudgment");
  const sourceCounts = asOptionalRecord(meta.sourceCounts);

  const date = asOptionalString(meta.date);
  if (!date) {
    throw new Error("brief.meta.date must be a string");
  }

  if (expectedDate && date !== expectedDate) {
    throw new Error(`brief.meta.date mismatch: expected ${expectedDate}, got ${date}`);
  }

  const quality = meta.dataQuality;
  const translationStatus = meta.translationStatus;

  return {
    date,
    generatedAt: asOptionalString(meta.generatedAt),
    quality: quality === "ok" || quality === "degraded" || quality === "critical" ? quality : undefined,
    headline: asOptionalString(aiJudgment.headline),
    displayHeadline: asOptionalString(meta.displayHeadline),
    translationStatus:
      translationStatus === "ok" || translationStatus === "partial" || translationStatus === "failed"
        ? translationStatus
        : undefined,
    newsAll: sourceCounts && typeof sourceCounts.newsAll === "number" ? sourceCounts.newsAll : undefined,
    xSignalAll: sourceCounts && typeof sourceCounts.xSignalAll === "number" ? sourceCounts.xSignalAll : undefined,
  };
}

function publicBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_R2_BASE_URL ?? process.env.R2_BASE_URL ?? null;
}

function useFixtureData(): boolean {
  return process.env.BRIEF_DATA_SOURCE === "fixture";
}

function useOutputData(): boolean {
  return process.env.BRIEF_DATA_SOURCE === "output";
}

function requirePublicBaseUrl(): string {
  const baseUrl = publicBaseUrl();
  if (!baseUrl) {
    throw new Error(
      "NEXT_PUBLIC_R2_BASE_URL is required. Set BRIEF_DATA_SOURCE=fixture only for explicit local fixture mode.",
    );
  }
  return baseUrl.replace(/\/$/, "");
}

export async function loadIndex(): Promise<BriefIndex> {
  if (useFixtureData()) {
    return parseBriefIndex(await readFixture<unknown>("index.json"));
  }

  if (useOutputData()) {
    return readOutputIndex();
  }

  return parseBriefIndex(await fetchJson<unknown>(`${requirePublicBaseUrl()}/index.json`));
}

export async function loadBriefByDate(date: string): Promise<BriefData> {
  if (useFixtureData()) {
    return parseBriefData(await readFixture<unknown>(`${date}.json`));
  }

  if (useOutputData()) {
    return parseBriefData(await readOutputBrief<unknown>(date));
  }

  return parseBriefData(await fetchJson<unknown>(`${requirePublicBaseUrl()}/briefs/${date}.json`));
}

export async function loadLatest(): Promise<BriefData> {
  const index = await loadIndex();
  const latestDate = index.dates[0];
  if (!latestDate) {
    throw new Error("index.json must include at least one date");
  }
  return loadBriefByDate(latestDate);
}

export async function loadArchiveSummaryByDate(date: string): Promise<ArchiveBriefSummary> {
  if (useFixtureData()) {
    return parseArchiveSummary(await readFixture<unknown>(`${date}.json`), date);
  }

  if (useOutputData()) {
    return parseArchiveSummary(await readOutputBrief<unknown>(date), date);
  }

  return parseArchiveSummary(await fetchJson<unknown>(`${requirePublicBaseUrl()}/briefs/${date}.json`), date);
}

export const fetchIndex = cache(async (): Promise<BriefIndex> => {
  return loadIndex();
});

export const fetchLatest = cache(async (): Promise<BriefData> => {
  return loadLatest();
});

export const fetchBriefByDate = cache(async (date: string): Promise<BriefData> => {
  return loadBriefByDate(date);
});

export const fetchArchiveSummaryByDate = cache(async (date: string): Promise<ArchiveBriefSummary> => {
  return loadArchiveSummaryByDate(date);
});
