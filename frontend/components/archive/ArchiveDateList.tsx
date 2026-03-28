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
    <section className="px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <p className="section-title">아카이브</p>
            <h1 className="section-headline max-w-4xl">날짜별 브리핑을 정적 발행본 그대로 다시 읽습니다.</h1>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/52">
            홈의 실시간 톤을 유지하면서도, 발행일 기준 저장본을 한 번에 훑을 수 있는 인덱스입니다.
          </p>
        </div>

        <div className="grid gap-4">
          {items.map((item) => (
            <Link
              key={item.date}
              href={`/archive/${item.date}`}
              className="group rounded-[24px] border border-white/10 bg-white/[0.02] p-6 transition-all duration-300 hover:border-white/24 hover:bg-white/[0.04]"
            >
              <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="text-sm font-mono tracking-tight text-[#00ffff]">{item.date}</span>
                    <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-white/34">
                      {item.generatedAt ? `${formatIssueTime(item.generatedAt)} KST` : "시각 없음"}
                    </span>
                  </div>
                  <p className="max-w-4xl text-[1.05rem] leading-8 text-white md:text-[1.15rem]">
                    {item.displayHeadline && hasUsableHeadline(item.displayHeadline)
                      ? item.displayHeadline
                      : item.headline && hasUsableHeadline(item.headline)
                        ? displayHeadline(item.headline)
                        : `${item.date} 발행본`}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full border border-white/10 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-white/56">
                      {qualityLabel(item.quality ?? "ok")}
                    </span>
                    {item.translationStatus ? (
                      <span className="rounded-full border border-white/10 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-white/42">
                        {translationLabel(item.translationStatus)}
                      </span>
                    ) : null}
                    {(item.newsAll ?? 0) > 0 || (item.xSignalAll ?? 0) > 0 ? (
                      <span className="rounded-full border border-white/10 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-white/42">
                        뉴스 {item.newsAll ?? 0} · X {item.xSignalAll ?? 0}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-2 self-end text-[10px] font-mono uppercase tracking-[0.22em] text-white/34 transition group-hover:text-white">
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
