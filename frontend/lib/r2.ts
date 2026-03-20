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

export async function fetchIndex(): Promise<BriefIndex> {
  const baseUrl = publicBaseUrl();
  const payload = baseUrl
    ? await fetchJson<unknown>(`${baseUrl.replace(/\/$/, "")}/index.json`)
    : await readFixture<unknown>("index.json");
  return parseBriefIndex(payload);
}

export async function fetchLatest(): Promise<BriefData> {
  const baseUrl = publicBaseUrl();
  const payload = baseUrl
    ? await fetchJson<unknown>(`${baseUrl.replace(/\/$/, "")}/briefs/latest.json`)
    : await readFixture<unknown>("latest.json");
  return parseBriefData(payload);
}

export async function fetchBriefByDate(date: string): Promise<BriefData> {
  const baseUrl = publicBaseUrl();
  const payload = baseUrl
    ? await fetchJson<unknown>(`${baseUrl.replace(/\/$/, "")}/briefs/${date}.json`)
    : await readFixture<unknown>(`${date}.json`);
  return parseBriefData(payload);
}
