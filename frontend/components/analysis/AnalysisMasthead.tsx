"use client";

import type { GrangerCorrection } from "@schema/analysis.types";

export function AnalysisMasthead({
  referenceDate,
  generatedAtUtc,
  correction,
  staleWarning,
}: {
  referenceDate: string;
  generatedAtUtc: string;
  correction: GrangerCorrection;
  staleWarning: boolean;
}) {
  const generatedKst = (() => {
    try {
      return new Date(generatedAtUtc).toLocaleString("ko-KR", {
        timeZone: "Asia/Seoul",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return generatedAtUtc;
    }
  })();

  return (
    <div className="border-b border-white/10">
      {staleWarning && (
        <div className="border-b border-[var(--accent-warning)]/30 bg-[var(--accent-warning)]/8 px-6 py-3">
          <p className="font-mono text-[0.75rem] tracking-[0.08em] text-[var(--accent-warning)]">
            ⚠ 기준일 {referenceDate} — 최신 분석 데이터가 아닐 수 있습니다
          </p>
        </div>
      )}
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-12 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="mb-2 font-mono text-[0.7rem] uppercase tracking-[0.18em] text-[var(--text-muted)]">
            Analysis
          </p>
          <h1
            className="text-[2.4rem] leading-[1.1] tracking-[-0.03em] text-white md:text-[3.2rem]"
            style={{ fontFamily: "var(--font-instrument-serif)", fontStyle: "italic" }}
          >
            Sentiment Insight
          </h1>
          <p className="mt-3 max-w-lg text-[0.95rem] leading-7 text-[var(--text-secondary)]">
            뉴스 감성이 시장에 먼저 영향을 주는지, 아니면 시장이 감성을 이끄는지 —
            통계적으로 검증하고 어떤 지표가 신호에 얼마나 기여하는지 분해합니다.
          </p>
          <p className="mt-2 max-w-lg text-[0.8rem] leading-6 text-[var(--text-muted)]">
            매일 파이프라인이 실행될 때마다 갱신됩니다. 단순 상관이 아닌 시간 순서 기반 인과 분석입니다.
          </p>
        </div>
        <div className="shrink-0 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3 font-mono text-[0.72rem]">
            <MetaItem label="기준일" value={referenceDate} />
            <MetaItem label="생성" value={generatedKst} />
            <MetaItem label="검정 수" value={`${correction.nTests} pairs`} />
            <MetaItem label="보정" value={correction.method.toUpperCase()} accent />
          </dl>
        </div>
      </div>
    </div>
  );
}

function MetaItem({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div>
      <dt className="uppercase tracking-[0.12em] text-[var(--text-muted)]">{label}</dt>
      <dd
        className={`mt-0.5 tracking-[0.04em] ${accent ? "text-[var(--accent-primary)]" : "text-white/80"}`}
      >
        {value}
      </dd>
    </div>
  );
}
