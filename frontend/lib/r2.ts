import { cache } from "react";
import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BriefData, BriefIndex } from "@schema/brief.types";

import { parseBriefData, parseBriefIndex } from "./brief-schema";

const fixtureDir = path.join(process.cwd(), "fixtures");
const requestVersion =
  process.env.BRIEF_DATA_BUILD_ID ??
  process.env.GITHUB_SHA ??
  process.env.VERCEL_GIT_COMMIT_SHA ??
  `local-${Date.now()}`;

async function readFixture<T>(name: string): Promise<T> {
  const fullPath = path.join(fixtureDir, name);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw) as T;
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

function publicBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_R2_BASE_URL ?? process.env.R2_BASE_URL ?? null;
}

function useFixtureData(): boolean {
  return process.env.BRIEF_DATA_SOURCE === "fixture";
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
  const payload = useFixtureData()
    ? await readFixture<unknown>("index.json")
    : await fetchJson<unknown>(`${requirePublicBaseUrl()}/index.json`);
  return parseBriefIndex(payload);
}

export async function loadBriefByDate(date: string): Promise<BriefData> {
  const payload = useFixtureData()
    ? await readFixture<unknown>(`${date}.json`)
    : await fetchJson<unknown>(`${requirePublicBaseUrl()}/briefs/${date}.json`);
  return parseBriefData(payload);
}

export async function loadLatest(): Promise<BriefData> {
  const index = await loadIndex();
  const latestDate = index.dates[0];
  if (!latestDate) {
    throw new Error("index.json must include at least one date");
  }
  return loadBriefByDate(latestDate);
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
