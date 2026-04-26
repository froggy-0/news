import Link from "next/link";

import type { BriefMeta } from "@schema/brief.types";

import {
  formatIssueTime,
  formatPublicationDate,
  qualityLabel,
  translationLabel,
} from "@/lib/format";

export function MetadataSection({
  meta,
  archiveHref,
}: {
  meta: BriefMeta;
  archiveHref?: `/archive/${string}`;
}) {
  return (
    <section className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <p className="section-title">데이터 기준 / 상태</p>
            <h2 className="section-headline max-w-4xl">오늘 화면이 어떤 기준과 상태 위에서 렌더링됐는지 남깁니다.</h2>
          </div>
          {archiveHref ? (
            <Link
              href={archiveHref}
              className="inline-flex items-center justify-center rounded-full border border-white/10 px-4 py-2 text-[10px] font-mono uppercase tracking-[0.22em] text-white/58 transition hover:border-[var(--accent-primary)]/30 hover:text-white"
            >
              전체 발행본 보기
            </Link>
          ) : null}
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusCard label="발행 기준일" value={formatPublicationDate(meta.date)} />
          <StatusCard label="생성 시각" value={`${formatIssueTime(meta.generatedAt)} KST`} />
          <StatusCard label="데이터 품질" value={qualityLabel(meta.dataQuality)} tone={meta.dataQuality === "ok" ? "positive" : "warning"} />
          <StatusCard
            label="번역 상태"
            value={translationLabel(meta.translationStatus)}
            tone={meta.translationStatus === "ok" ? "positive" : meta.translationStatus === "failed" ? "warning" : "muted"}
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="section-shell rounded-[28px] p-6">
            <p className="section-title">수집 커버리지</p>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <CoverageBlock
                title="뉴스"
                summary={`${meta.sourceCounts.newsCandidates}건 수집 → ${meta.sourceCounts.newsAll}건 노출`}
                detail={`랭킹 ${meta.sourceCounts.newsRanked}건 / featured ${meta.sourceCounts.newsFeatured}건`}
              />
              <CoverageBlock
                title="X 시그널"
                summary={`${meta.sourceCounts.xSignalCandidates}건 수집 → ${meta.sourceCounts.xSignalAll}건 노출`}
                detail={`랭킹 ${meta.sourceCounts.xSignalRanked}건 / featured ${meta.sourceCounts.xSignalFeatured}건`}
              />
            </div>
          </div>

          <div className="section-shell rounded-[28px] p-6">
            <p className="section-title">품질 메모</p>
            {meta.qualityNotes.length > 0 ? (
              <ul className="mt-4 space-y-3 text-sm leading-7 text-white/70">
                {meta.qualityNotes.map((note) => (
                  <li key={note} className="border-l border-white/10 pl-4">
                    {note}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-sm leading-7 text-white/60">
                품질 저하 메모 없이 정상 수집된 발행본입니다.
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function StatusCard({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: string;
  tone?: "positive" | "warning" | "muted";
}) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.02] p-5">
      <p className="text-[9px] font-mono uppercase tracking-[0.24em] text-white/28">{label}</p>
      <p
        className={`mt-3 text-sm leading-6 ${
          tone === "positive"
            ? "text-[var(--accent-primary)]"
            : tone === "warning"
              ? "text-[#ffd166]"
              : "text-white/78"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function CoverageBlock({
  title,
  summary,
  detail,
}: {
  title: string;
  summary: string;
  detail: string;
}) {
  return (
    <div className="rounded-[22px] border border-white/8 bg-black/35 p-5">
      <p className="text-[9px] font-mono uppercase tracking-[0.24em] text-white/28">{title}</p>
      <p className="mt-3 text-sm leading-6 text-white/78">{summary}</p>
      <p className="mt-2 text-[11px] font-mono leading-5 text-white/38">{detail}</p>
    </div>
  );
}
