import Link from "next/link";

import { displayHeadline, formatIssueTime, qualityLabel } from "@/lib/format";

type ArchiveItem = {
  date: string;
  generatedAt?: string;
  quality?: "ok" | "degraded" | "critical";
  headline?: string;
  displayHeadline?: string;
};

export function ArchiveDateList({ items }: { items: ArchiveItem[] }) {
  return (
    <section className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-8 grid gap-5 border-b border-white/8 pb-7 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          <p className="section-title">아카이브</p>
          <h1 className="display-headline mt-4 text-[2.5rem] md:text-[4.2rem]">날짜별 브리핑 아카이브</h1>
        </div>
        <p className="hero-support max-w-sm">
          홈 화면의 실시간 티커 없이, 발행일 기준으로 저장된 브리핑을 다시 읽을 수 있는 정적 인덱스입니다.
        </p>
      </div>
      <div className="divide-y divide-white/8">
        {items.map((item) => (
          <Link
            key={item.date}
            href={`/archive/${item.date}`}
            className="grid gap-5 py-6 transition hover:bg-white/[0.02] md:grid-cols-[170px_minmax(0,1fr)_110px] md:px-2"
          >
            <div className="space-y-2">
              <p className="font-mono text-[11px] tracking-[0.22em] text-[var(--accent-primary)] uppercase">{item.date}</p>
              <p className="font-mono text-[10px] tracking-[0.16em] text-[var(--text-muted)] uppercase">
                {item.generatedAt ? formatIssueTime(item.generatedAt) : "08:00"} KST
              </p>
            </div>
            <p className="text-lg leading-8 text-[var(--text-primary)]">
              {item.displayHeadline
                ? item.displayHeadline
                : item.headline
                  ? displayHeadline(item.headline)
                  : "브리핑을 열어 상세 내용을 확인하세요."}
            </p>
            <div className="md:text-right">
              <span className="inline-flex rounded-full border border-white/10 px-3 py-1 font-mono text-[10px] tracking-[0.18em] text-[var(--text-secondary)] uppercase">
                {qualityLabel(item.quality ?? "ok")}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
