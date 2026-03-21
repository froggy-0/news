import { cache } from "react";
import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BriefData, BriefIndex } from "@schema/brief.types";

import { parseBriefData, parseBriefIndex } from "./brief-schema";

const fixtureDir = path.join(process.cwd(), "fixtures");

async function readFixture<T>(name: string): Promise<T> {
  const fullPath = path.join(fixtureDir, name);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw) as T;
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    cache: "force-cache",
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }

  return (await response.json()) as T;
}

function publicBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_R2_BASE_URL ?? process.env.R2_BASE_URL ?? null;
}

export const fetchIndex = cache(async (): Promise<BriefIndex> => {
  const baseUrl = publicBaseUrl();
  const payload = baseUrl
    ? await fetchJson<unknown>(`${baseUrl.replace(/\/$/, "")}/index.json`)
    : await readFixture<unknown>("index.json");
  return parseBriefIndex(payload);
});

export const fetchLatest = cache(async (): Promise<BriefData> => {
  const index = await fetchIndex();
  const latestDate = index.dates[0];
  if (!latestDate) {
    throw new Error("index.json must include at least one date");
  }
  return fetchBriefByDate(latestDate);
});

export const fetchBriefByDate = cache(async (date: string): Promise<BriefData> => {
  const baseUrl = publicBaseUrl();
  const payload = baseUrl
    ? await fetchJson<unknown>(`${baseUrl.replace(/\/$/, "")}/briefs/${date}.json`)
    : await readFixture<unknown>(`${date}.json`);
  return parseBriefData(payload);
});
