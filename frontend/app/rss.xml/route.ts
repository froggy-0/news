import { fetchBriefByDate, fetchIndex } from "@/lib/r2";

export async function GET() {
  const index = await fetchIndex();
  const briefs = await Promise.all(index.dates.map((date) => fetchBriefByDate(date)));

  const items = briefs
    .map(
      (brief) => `
        <item>
          <title><![CDATA[${brief.aiJudgment.headline}]]></title>
          <link>https://example.com/archive/${brief.meta.date}</link>
          <guid>https://example.com/archive/${brief.meta.date}</guid>
          <pubDate>${new Date(brief.meta.generatedAt).toUTCString()}</pubDate>
          <description><![CDATA[${brief.aiJudgment.body}]]></description>
        </item>`,
    )
    .join("");

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SOVEREIGN BRIEF</title>
    <link>https://example.com/</link>
    <description>미국 시장 브리핑 RSS 피드</description>
    ${items}
  </channel>
</rss>`;

  return new Response(body, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
    },
  });
}
