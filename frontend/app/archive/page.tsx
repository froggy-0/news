import type { Metadata } from "next";

import { ArchiveDateList } from "@/components/archive/ArchiveDateList";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { fetchBriefByDate, fetchIndex } from "@/lib/r2";

export const metadata: Metadata = {
  title: "브리핑 아카이브",
  description: "날짜별 SOVEREIGN BRIEF 발행본을 다시 확인할 수 있습니다.",
};

export default async function ArchivePage() {
  const index = await fetchIndex();
  const items = await Promise.all(
    index.dates.map(async (date) => {
      const brief = await fetchBriefByDate(date);
      return {
        date,
        generatedAt: brief.meta.generatedAt,
        quality: brief.meta.dataQuality,
        headline: brief.aiJudgment.headline,
        displayHeadline: brief.meta.displayHeadline,
      };
    }),
  );

  return (
    <main className="space-y-8">
      <SiteHeader generatedAt={index.updatedAt} variant="archive" />
      <ArchiveDateList items={items} />
    </main>
  );
}
