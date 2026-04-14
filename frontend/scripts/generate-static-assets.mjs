import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const frontendDir = process.cwd();
const fixtureDir = path.join(frontendDir, "fixtures");
const outputDir = path.resolve(frontendDir, "..", "output");
const publicDir = path.join(frontendDir, "public");
const baseUrl = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://example.com").replace(/\/$/, "");
const dataBaseUrl = process.env.NEXT_PUBLIC_R2_BASE_URL ?? process.env.R2_BASE_URL ?? null;
const useFixtureData = process.env.BRIEF_DATA_SOURCE === "fixture";
const useOutputData = process.env.BRIEF_DATA_SOURCE === "output";
const buildVersion =
  process.env.BRIEF_DATA_BUILD_ID ?? process.env.GITHUB_SHA ?? `local-${Date.now()}`;
const outputBriefPattern = /^briefs_(\d{4}-\d{2}-\d{2})\.json$/;

function requireAbsoluteHttpUrl(value, envName) {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error("invalid protocol");
    }
    return value.replace(/\/$/, "");
  } catch {
    throw new Error(`${envName} must be an absolute http(s) URL. Received: ${value}`);
  }
}

async function readLocalJson(name) {
  const raw = await readFile(path.join(fixtureDir, name), "utf8");
  return JSON.parse(raw);
}

async function readOutputJson(date) {
  const raw = await readFile(path.join(outputDir, `briefs_${date}.json`), "utf8");
  return JSON.parse(raw);
}

async function readOutputIndex() {
  const entries = await readdir(outputDir, { withFileTypes: true });
  const candidates = entries
    .filter((entry) => entry.isFile())
    .map((entry) => outputBriefPattern.exec(entry.name)?.[1] ?? null)
    .filter((date) => date !== null);
  const validated = await Promise.all(
    candidates.map(async (date) => {
      try {
        await readOutputJson(date);
        return date;
      } catch {
        return null;
      }
    }),
  );
  const dates = validated
    .filter((date) => date !== null)
    .sort((left, right) => right.localeCompare(left));

  return {
    dates,
    updatedAt: new Date().toISOString(),
  };
}

async function readRemoteJson(url) {
  const requestUrl = new URL(url);
  requestUrl.searchParams.set("_build", buildVersion);
  const response = await fetch(requestUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${requestUrl}: ${response.status}`);
  }
  return response.json();
}

async function readIndex() {
  if (useFixtureData) {
    return readLocalJson("index.json");
  }
  if (useOutputData) {
    return readOutputIndex();
  }
  if (!dataBaseUrl) {
    throw new Error(
      "NEXT_PUBLIC_R2_BASE_URL is required. Set BRIEF_DATA_SOURCE=fixture or output only for explicit local builds.",
    );
  }
  return readRemoteJson(`${requireAbsoluteHttpUrl(dataBaseUrl, "NEXT_PUBLIC_R2_BASE_URL")}/index.json`);
}

async function readBrief(date) {
  if (useFixtureData) {
    return readLocalJson(`${date}.json`);
  }
  if (useOutputData) {
    return readOutputJson(date);
  }
  if (!dataBaseUrl) {
    throw new Error(
      "NEXT_PUBLIC_R2_BASE_URL is required. Set BRIEF_DATA_SOURCE=fixture or output only for explicit local builds.",
    );
  }
  const index = await readIndex();
  return readRemoteBrief(index, date);
}

function normalizeRemotePath(pathValue) {
  return pathValue.replace(/^\/+/, "");
}

function isRenderableBriefPayload(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const meta = value.meta;
  const aiJudgment = value.aiJudgment;

  return (
    meta &&
    typeof meta === "object" &&
    !Array.isArray(meta) &&
    typeof meta.date === "string" &&
    aiJudgment &&
    typeof aiJudgment === "object" &&
    !Array.isArray(aiJudgment) &&
    typeof aiJudgment.headline === "string" &&
    typeof aiJudgment.body === "string"
  );
}

function resolveRemoteBriefCandidates(index, date) {
  const candidates = [];
  const pushCandidate = (pathValue) => {
    if (!pathValue || typeof pathValue !== "string") {
      return;
    }
    const normalized = normalizeRemotePath(pathValue);
    if (!candidates.includes(normalized)) {
      candidates.push(normalized);
    }
  };

  if (index?.latest?.date === date && typeof index.latest.path === "string" && index.latest.path.length > 0) {
    pushCandidate(index.latest.path);
  }

  const datedEntry = Array.isArray(index?.entriesByDate)
    ? index.entriesByDate.find((entry) => entry && entry.date === date)
    : null;
  const datedRuns = Array.isArray(datedEntry?.runs) ? datedEntry.runs : [];
  for (const run of datedRuns) {
    pushCandidate(run?.path);
  }

  pushCandidate(`curated/btc/${date}.json`);
  pushCandidate(`briefs/${date}.json`);

  return candidates;
}

async function readRemoteBrief(index, date) {
  const baseUrl = requireAbsoluteHttpUrl(dataBaseUrl, "NEXT_PUBLIC_R2_BASE_URL");
  const candidates = resolveRemoteBriefCandidates(index, date);
  let lastError = null;

  for (const remotePath of candidates) {
    try {
      const payload = await readRemoteJson(`${baseUrl}/${remotePath}`);
      if (!isRenderableBriefPayload(payload)) {
        lastError = new Error(`Payload at ${remotePath} is not a renderable brief`);
        continue;
      }
      return payload;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  throw lastError ?? new Error(`Unable to load remote brief for ${date}`);
}

function renderRssItem(brief) {
  return `
    <item>
      <title><![CDATA[${brief.aiJudgment.headline}]]></title>
      <link>${baseUrl}/archive/${brief.meta.date}</link>
      <guid>${baseUrl}/archive/${brief.meta.date}</guid>
      <pubDate>${new Date(brief.meta.generatedAt).toUTCString()}</pubDate>
      <description><![CDATA[${brief.aiJudgment.body}]]></description>
    </item>`;
}

async function writeStaticAssets() {
  const index = await readIndex();
  if (!index.dates[0]) {
    throw new Error("index.json must include at least one date");
  }
  const briefResults = await Promise.allSettled(index.dates.map((date) => readBrief(date)));
  const briefs = briefResults
    .filter((result) => result.status === "fulfilled")
    .map((result) => result.value);
  if (!briefs.length) {
    const failed = briefResults.find((result) => result.status === "rejected");
    throw failed?.reason ?? new Error("No renderable briefs were available for RSS generation");
  }
  const rssItems = briefs.map((brief) => renderRssItem(brief)).join("");
  const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SOVEREIGN BRIEF</title>
    <link>${baseUrl}/</link>
    <description>미국 시장 브리핑 RSS 피드</description>
    ${rssItems}
  </channel>
</rss>
`;
  const llms = `# SOVEREIGN BRIEF

이 서비스는 미국 기술주와 비트코인 시장 흐름을 한국어 브리핑으로 제공합니다.

## 주요 경로
- /
- /archive
- /rss.xml

## 업데이트 주기
- KST 오전 8시 기준 공개 경험을 목표로 합니다.
- 실제 공개 시점은 파이프라인 완료와 데이터 게시 시점을 따릅니다.
`;

  await mkdir(publicDir, { recursive: true });
  await writeFile(path.join(publicDir, "rss.xml"), rss, "utf8");
  await writeFile(path.join(publicDir, "llms.txt"), llms, "utf8");
}

await writeStaticAssets();
