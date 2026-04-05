export type HistoryMenuEntry = {
  date: string;
  href: `/archive/${string}`;
  isCurrent: boolean;
};

export function buildHistoryEntries(dates: string[], currentDate?: string): HistoryMenuEntry[] {
  return dates.map((date) => ({
    date,
    href: `/archive/${date}` as const,
    isCurrent: currentDate === date,
  }));
}
