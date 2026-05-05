import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import type { BriefData } from "@schema/brief.types";

import { loadBriefByDate, loadRenderableIndex } from "../lib/r2";

const frontendDir = process.cwd();
const publicDir = path.join(frontendDir, "public");
const siteBaseUrl = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://example.com").replace(/\/$/, "");

function renderRssItem(brief: BriefData): string {
  return `
    <item>
      <title><![CDATA[${brief.aiJudgment.headline}]]></title>
      <link>${siteBaseUrl}/archive/${brief.meta.date}</link>
      <guid>${siteBaseUrl}/archive/${brief.meta.date}</guid>
      <pubDate>${new Date(brief.meta.generatedAt).toUTCString()}</pubDate>
      <description><![CDATA[${brief.aiJudgment.body}]]></description>
    </item>`;
}

async function writeStaticAssets(): Promise<void> {
  const index = await loadRenderableIndex();
  if (!index.dates[0]) {
    throw new Error("index.json must include at least one date");
  }

  const briefResults = await Promise.allSettled(index.dates.map((date) => loadBriefByDate(date)));
  const briefs = briefResults
    .filter((result): result is PromiseFulfilledResult<BriefData> => result.status === "fulfilled")
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
    <link>${siteBaseUrl}/</link>
    <description>비트코인·크립토 시장 브리핑 RSS 피드</description>
    ${rssItems}
  </channel>
</rss>
`;
  const llms = `# SOVEREIGN BRIEF

이 서비스는 비트코인, ETF, 달러·금리, 크립토 시장 흐름을 한국어 브리핑으로 제공합니다.

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

void (async () => {
  await writeStaticAssets();
})();
