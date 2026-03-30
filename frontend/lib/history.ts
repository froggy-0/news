import type { BriefMeta } from "@schema/brief.types";

import { qualityLabel, translationLabel } from "@/lib/format";

export type HistoryMenuEntry = {
  date: string;
  href: `/archive/${string}`;
  isCurrent: boolean;
};

export type DrawerStatusCard = {
  label: string;
  value: string;
  tone?: "positive" | "warning" | "muted";
};

export function buildHistoryEntries(dates: string[], currentDate?: string): HistoryMenuEntry[] {
  return dates.map((date) => ({
    date,
    href: `/archive/${date}` as const,
    isCurrent: currentDate === date,
  }));
}

export function buildMetaStatusCards(meta: BriefMeta): DrawerStatusCard[] {
  return [
    {
      label: "데이터 상태",
      value: qualityLabel(meta.dataQuality),
      tone: meta.dataQuality === "ok" ? "positive" : "warning",
    },
    {
      label: "언어 상태",
      value: translationLabel(meta.translationStatus),
      tone:
        meta.translationStatus === "ok"
          ? "positive"
          : meta.translationStatus === "failed"
            ? "warning"
            : "muted",
    },
    {
      label: "수집 범위",
      value: `뉴스 ${meta.sourceCounts.newsAll}건 · X ${meta.sourceCounts.xSignalAll}건`,
      tone: "muted",
    },
  ];
}
