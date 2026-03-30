import Link from "next/link";

import type { DrawerStatusCard, HistoryMenuEntry } from "@/lib/history";

import { HistoryDrawerClient } from "./HistoryDrawerClient";

export function SiteHeader({
  variant = "home",
  historyEntries,
  statusCards,
  currentDate,
}: {
  variant?: "home" | "archive-list" | "archive-detail";
  historyEntries: HistoryMenuEntry[];
  statusCards: DrawerStatusCard[];
  currentDate?: string;
}) {
  const variantCopy =
    variant === "home"
      ? "Live Intelligence"
      : variant === "archive-list"
        ? "Archive Index"
        : "Archive Detail";

  return (
    <header className="fixed inset-x-0 top-0 z-[70] border-b border-white/10 bg-black/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-[1440px] items-center justify-between gap-4 px-5 md:px-7">
        <div className="flex min-w-0 items-center gap-4">
          <Link
            href="/"
            className="text-base font-black tracking-[-0.06em] text-white transition-colors hover:text-[var(--accent-primary)] md:text-xl"
          >
            SOVEREIGN BRIEF
          </Link>
          <div className="hidden items-center gap-2 md:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--status-positive)] shadow-[0_0_10px_rgba(0,255,102,0.65)]" />
            <span className="label-meta text-white/42">
              {variantCopy}
            </span>
          </div>
        </div>

        <div className="flex items-center">
          <HistoryDrawerClient
            entries={historyEntries}
            statusCards={statusCards}
            currentDate={currentDate}
          />
        </div>
      </div>
    </header>
  );
}
