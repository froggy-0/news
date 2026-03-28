import type { Metadata } from "next";

import { ArchiveDateList } from "@/components/archive/ArchiveDateList";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { buildHistoryEntries, buildMetaStatusCards } from "@/lib/history";
import { fetchBriefByDate, fetchIndex } from "@/lib/r2";

export const metadata: Metadata = {
  title: "브리핑 아카이브",
  description: "날짜별 SOVEREIGN BRIEF 발행본을 다시 확인할 수 있습니다.",
};

export default async function ArchivePage() {
  const index = await fetchIndex();
  const briefs = await Promise.all(index.dates.map((date) => fetchBriefByDate(date)));
  const latestBrief = briefs[0] ?? null;
  const items = briefs.map((brief) => ({
    date: brief.meta.date,
    generatedAt: brief.meta.generatedAt,
    quality: brief.meta.dataQuality,
    headline: brief.aiJudgment.headline,
    displayHeadline: brief.meta.displayHeadline,
    translationStatus: brief.meta.translationStatus,
    newsAll: brief.meta.sourceCounts.newsAll,
    xSignalAll: brief.meta.sourceCounts.xSignalAll,
  }));

  return (
    <main className="pb-6">
      <SiteHeader
        variant="archive-list"
        historyEntries={buildHistoryEntries(index.dates)}
        statusCards={
          latestBrief
            ? buildMetaStatusCards(latestBrief.meta)
            : [
                { label: "Archive", value: `${index.dates.length}건`, tone: "muted" },
                { label: "Updated", value: index.updatedAt, tone: "muted" },
              ]
        }
      />
      <ArchiveDateList items={items} />
    </main>
  );
}
