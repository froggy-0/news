import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { displayHeadline, formatIssueTime, hasUsableHeadline, qualityLabel, translationLabel } from "@/lib/format";

type ArchiveItem = {
  date: string;
  generatedAt?: string;
  quality?: "ok" | "degraded" | "critical";
  headline?: string;
  displayHeadline?: string;
  translationStatus?: "ok" | "partial" | "failed";
  newsAll?: number;
  xSignalAll?: number;
};

export function ArchiveDateList({ items }: { items: ArchiveItem[] }) {
  return (
    <section className="relative z-10 px-6 py-24 md:px-20">
      <div className="mx-auto flex w-full flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.15em] text-[var(--accent-primary)] md:text-[13px]">
              ARCHIVE INDEX
            </p>
            <h1 className="max-w-4xl text-[32px] font-bold leading-[1.3] text-[var(--smoke)] md:text-[52px] md:leading-[1.23]">
              날짜별 브리핑을 다시 읽습니다.
            </h1>
          </div>
          <p className="max-w-md text-sm leading-7 text-[var(--taupe)]">
            홈의 실시간 톤을 유지하면서도, 발행일 기준 저장본을 한 번에 훑을 수 있는 인덱스입니다.
          </p>
        </div>

        <div className="grid gap-4">
          {items.map((item) => (
            <Link
              key={item.date}
              href={`/archive/${item.date}`}
              className="group rounded-md border border-[rgba(169,146,125,0.14)] bg-[rgba(242,244,243,0.03)] p-6 transition-colors duration-300 hover:border-[rgba(169,146,125,0.30)] hover:bg-[rgba(242,244,243,0.05)]"
            >
              <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="text-sm font-medium text-[var(--accent-primary)]">{item.date}</span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-[var(--taupe)]/42">
                      {item.generatedAt ? `${formatIssueTime(item.generatedAt)} KST` : "시각 없음"}
                    </span>
                  </div>
                  <p className="max-w-4xl text-[1.05rem] leading-8 text-[var(--smoke)] md:text-[1.15rem]">
                    {item.displayHeadline && hasUsableHeadline(item.displayHeadline)
                      ? item.displayHeadline
                      : item.headline && hasUsableHeadline(item.headline)
                        ? displayHeadline(item.headline)
                        : `${item.date} 발행본`}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-md border border-[rgba(169,146,125,0.14)] px-3 py-1 text-[9px] uppercase tracking-[0.14em] text-[var(--taupe)]/70">
                      {qualityLabel(item.quality ?? "ok")}
                    </span>
                    {item.translationStatus ? (
                      <span className="rounded-md border border-[rgba(169,146,125,0.14)] px-3 py-1 text-[9px] uppercase tracking-[0.14em] text-[var(--taupe)]/55">
                        {translationLabel(item.translationStatus)}
                      </span>
                    ) : null}
                    {(item.newsAll ?? 0) > 0 || (item.xSignalAll ?? 0) > 0 ? (
                      <span className="rounded-md border border-[rgba(169,146,125,0.14)] px-3 py-1 text-[9px] uppercase tracking-[0.14em] text-[var(--taupe)]/55">
                        뉴스 {item.newsAll ?? 0} · X {item.xSignalAll ?? 0}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-2 self-end text-[10px] uppercase tracking-[0.14em] text-[var(--taupe)]/45 transition group-hover:text-[var(--smoke)]">
                  <span>열기</span>
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
