import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const frontendDir = process.cwd();
const fixtureDir = path.join(frontendDir, "fixtures");
const publicDir = path.join(frontendDir, "public");
const baseUrl = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://example.com").replace(/\/$/, "");
const dataBaseUrl = process.env.NEXT_PUBLIC_R2_BASE_URL ?? process.env.R2_BASE_URL ?? null;

async function readLocalJson(name) {
  const raw = await readFile(path.join(fixtureDir, name), "utf8");
  return JSON.parse(raw);
}

async function readRemoteJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }
  return response.json();
}

async function readIndex() {
  if (!dataBaseUrl) {
    return readLocalJson("index.json");
  }
  return readRemoteJson(`${dataBaseUrl.replace(/\/$/, "")}/index.json`);
}

async function readBrief(date) {
  if (!dataBaseUrl) {
    return readLocalJson(`${date}.json`);
  }
  return readRemoteJson(`${dataBaseUrl.replace(/\/$/, "")}/briefs/${date}.json`);
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
  const briefs = await Promise.all(index.dates.map((date) => readBrief(date)));
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
