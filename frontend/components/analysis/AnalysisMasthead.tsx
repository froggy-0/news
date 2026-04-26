"use client";

import React from "react";

import type { GrangerCorrection } from "@schema/analysis.types";
import type { AnalysisSummary, DerivedSignal } from "@/lib/analysis-derive";
import { formatAdjustedPValue, formatQualityStatus } from "@/lib/analysis-derive";

export function AnalysisMasthead({
  referenceDate,
  generatedAtUtc,
  correction,
  staleWarning,
  summary,
  schemaVersion,
  diagnosticsReady,
}: {
  referenceDate: string;
  generatedAtUtc: string;
  correction: GrangerCorrection;
  staleWarning: boolean;
  summary: AnalysisSummary;
  schemaVersion?: string;
  diagnosticsReady: boolean;
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
            기준일 {referenceDate} — 최신 분석 데이터가 아닐 수 있습니다
          </p>
        </div>
      )}
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-12 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="mb-2 font-mono text-[0.7rem] uppercase tracking-[0.18em] text-[var(--text-muted)]">
            Parquet-backed research console
          </p>
          <h1
            className="text-[2.4rem] leading-[1.1] tracking-[-0.03em] text-white md:text-[3.2rem]"
            style={{ fontFamily: "var(--font-instrument-serif)", fontStyle: "italic" }}
          >
            감성 알파 리서치 랩
          </h1>
          <p className="mt-3 max-w-lg text-[0.95rem] leading-7 text-[var(--text-secondary)]">
            뉴스 감성, BTC 시장 구조, ETF·선물 데이터를 하나의 검증 가능한 리서치 콘솔로
            묶어 선행성, 품질, alpha 후보를 함께 점검합니다.
          </p>
          <p className="mt-2 max-w-lg text-[0.8rem] leading-6 text-[var(--text-muted)]">
            Granger causality, PCA hybrid index, lag-only alpha validation, target diagnostics를
            같은 기준일의 parquet metadata와 연결해 읽습니다.
          </p>
          {!diagnosticsReady && (
            <div className="mt-5 max-w-xl rounded-2xl border border-[var(--accent-warning)]/24 bg-[var(--accent-warning)]/7 p-4">
              <p className="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-[var(--accent-warning)]">
                Diagnostic artifact pending
              </p>
              <p className="mt-2 text-[0.78rem] leading-6 text-white/56">
                현재 공개 JSON은 legacy 계약이라 parquet에 있는 data quality, alpha, target,
                raw metadata가 아직 모두 노출되지 않았습니다. 다음 sentiment-join 재실행 후
                v2 artifact가 publish되면 아래 진단 카드가 채워집니다.
              </p>
            </div>
          )}
        </div>
        <div className="shrink-0 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <dl className="grid grid-cols-1 gap-x-8 gap-y-3 font-mono text-[0.72rem] sm:grid-cols-2">
            <MetaItem label="기준일" value={referenceDate} />
            <MetaItem label="생성" value={generatedKst} />
            <MetaItem
              label="artifact"
              value={diagnosticsReady ? (schemaVersion ?? "v2") : "legacy v1"}
              accent={diagnosticsReady}
            />
            <MetaItem
              label="diagnostics"
              value={diagnosticsReady ? "complete" : "pending"}
              accent={diagnosticsReady}
              warning={!diagnosticsReady}
            />
            <MetaItem label="검정한 관계" value={`${correction.nTests}개`} />
            <MetaItem
              label="p-value 보정"
              value={`적용 (${correction.method.toUpperCase().replace("_", "-")})`}
              accent
            />
          </dl>
        </div>
      </div>
      <div className="mx-auto w-full max-w-6xl px-6 pb-8">
        <div
          className="grid gap-3 md:grid-cols-4"
          style={{ perspective: "1200px" }}
          aria-label="분석 핵심 요약"
        >
          <SummarySignalCard title="감성이 먼저" caption="뉴스 분위기 -> 시장" signal={summary.strongestForward} />
          <SummarySignalCard title="시장이 먼저" caption="시장 -> 뉴스 분위기" signal={summary.strongestReverse} />
          <SummaryMetricCard
            title="의미 있는 관계"
            value={`${summary.significantCount}`}
            caption="보정 p-value 0.05 미만"
            tone={summary.significantCount > 0 ? "cyan" : "muted"}
          />
          <SummaryMetricCard
            title="종합 신호 핵심"
            value={summary.topPcaDriver?.label ?? "종합 신호 없음"}
            caption={
              summary.topPcaDriver
                ? `${summary.topPcaDriver.loading >= 0 ? "+" : ""}${summary.topPcaDriver.loading.toFixed(3)} · 데이터 ${(summary.coverageRatio * 100).toFixed(1)}%`
                : `데이터 상태 ${formatQualityStatus(summary.qualityStatus)}`
            }
            tone={summary.topPcaDriver?.direction === "negative" ? "red" : "green"}
          />
        </div>
      </div>
    </div>
  );
}

function SummarySignalCard({
  title,
  caption,
  signal,
}: {
  title: string;
  caption: string;
  signal: DerivedSignal | null;
}) {
  const hasSignal = signal !== null;
  return (
    <div className="analysis-depth-panel group min-h-[124px] p-4 transition-transform duration-300 hover:-translate-y-1">
      <p className="font-mono text-[0.63rem] uppercase tracking-[0.16em] text-white/34">{title}</p>
      <p className="mt-1 font-mono text-[0.62rem] tracking-[0.08em] text-[var(--accent-primary)]/70">
        {caption}
      </p>
      <p className="mt-4 text-[0.9rem] font-semibold leading-5 text-white/86">
        {hasSignal ? signal.label : "뚜렷한 관계 없음"}
      </p>
      <p className="mt-2 font-mono text-[0.68rem] text-white/38">
        {hasSignal && signal.lag !== null
          ? `${signal.lag}일 전 · ${formatAdjustedPValue(signal.adjustedPValue)}${signal.significant ? " · 의미 있음" : ""}`
          : "검정값 없음"}
      </p>
    </div>
  );
}

function SummaryMetricCard({
  title,
  value,
  caption,
  tone,
}: {
  title: string;
  value: string;
  caption: string;
  tone: "cyan" | "green" | "red" | "muted";
}) {
  const color =
    tone === "green"
      ? "var(--accent-green)"
      : tone === "red"
        ? "var(--accent-down)"
        : tone === "cyan"
          ? "var(--accent-primary)"
          : "rgba(255,255,255,0.42)";
  return (
    <div className="analysis-depth-panel group min-h-[124px] p-4 transition-transform duration-300 hover:-translate-y-1">
      <p className="font-mono text-[0.63rem] uppercase tracking-[0.16em] text-white/34">{title}</p>
      <p
        className="mt-4 text-[1rem] font-semibold leading-5 text-white/88 md:text-[1.1rem]"
        style={{ color }}
      >
        {value}
      </p>
      <p className="mt-2 font-mono text-[0.68rem] text-white/38">{caption}</p>
    </div>
  );
}

function MetaItem({
  label,
  value,
  accent,
  warning,
}: {
  label: string;
  value: string;
  accent?: boolean;
  warning?: boolean;
}) {
  const valueClass = warning
    ? "text-[var(--accent-warning)]"
    : accent
      ? "text-[var(--accent-primary)]"
      : "text-white/80";
  return (
    <div>
      <dt className="uppercase tracking-[0.12em] text-[var(--text-muted)]">{label}</dt>
      <dd className={`mt-0.5 tracking-[0.04em] ${valueClass}`}>{value}</dd>
    </div>
  );
}
