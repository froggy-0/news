"use client";

import React from "react";
import { useMemo, useState } from "react";

import type { GrangerDirection, GrangerResult, GrangerSection } from "@schema/analysis.types";
import { formatAdjustedPValue, formatFeatureLabel, negLog10 } from "@/lib/analysis-derive";

type GroupKey = string;

type RowGroup = {
  key: GroupKey;
  predictor: string;
  target: string;
  direction: GrangerDirection;
  label: string;
  optimal: GrangerResult;
  allLags: GrangerResult[];
};

function groupKey(result: GrangerResult): GroupKey {
  return `${result.predictor}||${result.target}||${result.direction}`;
}

function formatPairLabel(result: Pick<GrangerResult, "predictor" | "target">): string {
  return `${formatFeatureLabel(result.predictor)} -> ${formatFeatureLabel(result.target)}`;
}

function fmtP(value: number | null): string {
  if (value === null) return "n/a";
  if (value < 0.001) return "<0.001";
  return value.toFixed(3);
}

function formatLag(value: number): string {
  return `${value}일 전`;
}

function buildGroups(results: GrangerResult[]): RowGroup[] {
  const map = new Map<GroupKey, GrangerResult[]>();
  for (const result of results) {
    const key = groupKey(result);
    map.set(key, [...(map.get(key) ?? []), result]);
  }

  return [...map.entries()]
    .map(([key, lags]) => {
      const allLags = [...lags].sort((a, b) => a.lag - b.lag);
      const optimal =
        allLags.find((result) => result.optimalLag) ??
        [...allLags].sort((a, b) => (a.pvalueAdjusted ?? 1) - (b.pvalueAdjusted ?? 1))[0];

      return {
        key,
        predictor: optimal.predictor,
        target: optimal.target,
        direction: optimal.direction,
        label: formatPairLabel(optimal),
        optimal,
        allLags,
      };
    })
    .sort((a, b) => {
      if (a.direction !== b.direction) return a.direction === "forward" ? -1 : 1;
      if (a.optimal.significant !== b.optimal.significant) {
        return a.optimal.significant ? -1 : 1;
      }
      return (a.optimal.pvalueAdjusted ?? 1) - (b.optimal.pvalueAdjusted ?? 1);
    });
}

export function GrangerSymmetric({ granger }: { granger: GrangerSection }) {
  const [activeLag, setActiveLag] = useState<string | null>(null);
  const [pinnedLag, setPinnedLag] = useState<string | null>(null);

  const groups = useMemo(() => buildGroups(granger.results), [granger.results]);
  const maxScore = useMemo(() => {
    const scores = granger.results.map((result) => negLog10(result.pvalueAdjusted)).sort((a, b) => a - b);
    return scores[Math.floor(scores.length * 0.95)] || 1;
  }, [granger.results]);

  const forward = groups.filter((group) => group.direction === "forward");
  const reverse = groups.filter((group) => group.direction === "reverse");

  if (!granger.executed) {
    return (
      <div className="flex min-h-[280px] items-center justify-center">
        <div className="text-center">
          <p className="font-mono text-[0.72rem] uppercase tracking-[0.18em] text-[var(--text-muted)]">
            시간 순서 검정 미수행
          </p>
          <p className="mt-2 text-[0.82rem] text-white/38">
            충분한 데이터가 쌓이면 며칠 전 지표가 오늘의 변화를 설명하는지 표시합니다.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[var(--accent-primary)]/80">
            먼저 움직인 신호
          </p>
          <p className="mt-2 max-w-2xl text-[0.82rem] leading-6 text-white/46">
            각 카드는 하나의 관계를 뜻합니다. 1일 전, 2일 전, 3일 전 중 어떤 간격에서
            설명력이 가장 좋았는지 비교합니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 font-mono text-[0.64rem] uppercase tracking-[0.12em]">
          <span className="rounded-full border border-[var(--accent-primary)]/24 bg-[var(--accent-primary)]/8 px-3 py-1 text-[var(--accent-primary)]">
            보정 p&lt;0.05
          </span>
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-white/36">
            시간 순서 기반 예측 관계
          </span>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <SignalColumn
          title="감성이 먼저"
          subtitle="뉴스 분위기 -> 시장"
          groups={forward}
          maxScore={maxScore}
          activeLag={activeLag}
          pinnedLag={pinnedLag}
          onHover={setActiveLag}
          onPin={(id) => setPinnedLag((current) => (current === id ? null : id))}
        />
        <SignalColumn
          title="시장이 먼저"
          subtitle="시장 -> 뉴스 분위기"
          groups={reverse}
          maxScore={maxScore}
          activeLag={activeLag}
          pinnedLag={pinnedLag}
          onHover={setActiveLag}
          onPin={(id) => setPinnedLag((current) => (current === id ? null : id))}
        />
      </div>
    </div>
  );
}

function SignalColumn({
  title,
  subtitle,
  groups,
  maxScore,
  activeLag,
  pinnedLag,
  onHover,
  onPin,
}: {
  title: string;
  subtitle: string;
  groups: RowGroup[];
  maxScore: number;
  activeLag: string | null;
  pinnedLag: string | null;
  onHover: (id: string | null) => void;
  onPin: (id: string) => void;
}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h3 className="font-mono text-[0.72rem] uppercase tracking-[0.16em] text-white/72">
          {title}
        </h3>
        <span className="font-mono text-[0.65rem] tracking-[0.1em] text-white/28">{subtitle}</span>
      </div>
      <div className="space-y-3">
        {groups.length > 0 ? (
          groups.map((group, index) => (
            <SignalCard
              key={group.key}
              group={group}
              maxScore={maxScore}
              index={index}
              activeLag={activeLag}
              pinnedLag={pinnedLag}
              onHover={onHover}
              onPin={onPin}
            />
          ))
        ) : (
          <div className="rounded-xl border border-white/8 bg-white/[0.025] p-5">
            <p className="font-mono text-[0.72rem] text-white/38">뚜렷한 관계가 없습니다.</p>
          </div>
        )}
      </div>
    </section>
  );
}

function SignalCard({
  group,
  maxScore,
  index,
  activeLag,
  pinnedLag,
  onHover,
  onPin,
}: {
  group: RowGroup;
  maxScore: number;
  index: number;
  activeLag: string | null;
  pinnedLag: string | null;
  onHover: (id: string | null) => void;
  onPin: (id: string) => void;
}) {
  const bestScore = negLog10(group.optimal.pvalueAdjusted);
  const strength = Math.min(bestScore / maxScore, 1);

  return (
    <article
      className="relative rounded-xl border border-white/10 bg-white/[0.025] p-4 transition duration-300 hover:-translate-y-0.5 hover:border-white/18 hover:bg-white/[0.04]"
      style={{ animation: `fadeLift 420ms ease-out ${index * 45}ms both` }}
    >
      <style>{`
        @keyframes fadeLift {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <p className="truncate text-[0.92rem] font-semibold text-white/86">{group.label}</p>
          <p className="mt-1 font-mono text-[0.65rem] text-white/32">
            가장 강함: {formatLag(group.optimal.lag)} · {formatAdjustedPValue(group.optimal.pvalueAdjusted)}
          </p>
        </div>
        <div className="flex items-center gap-2 font-mono text-[0.62rem] uppercase tracking-[0.12em]">
          <span
            className={`rounded-full px-2.5 py-1 ${
              group.optimal.significant
                ? "border border-[var(--accent-primary)]/30 bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]"
                : "border border-white/10 bg-white/[0.03] text-white/34"
            }`}
          >
            {group.optimal.significant ? "의미 있음" : "관찰"}
          </span>
          <span className="text-white/28">{Math.round(strength * 100)}%</span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2" role="list" aria-label={`${group.label} 날짜 간격`}>
        {group.allLags.map((lag) => {
          const id = `${group.key}|${lag.lag}`;
          const score = negLog10(lag.pvalueAdjusted);
          const pct = Math.min((score / maxScore) * 100, 100);
          const active = activeLag === id || pinnedLag === id;
          return (
            <button
              key={id}
              type="button"
              className={`relative rounded-lg border px-2 py-3 text-left transition ${
                active
                  ? "border-white/28 bg-white/[0.08]"
                  : "border-white/8 bg-black/20 hover:border-white/18 hover:bg-white/[0.05]"
              }`}
              onMouseEnter={() => onHover(id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(id)}
              onBlur={() => onHover(null)}
              onClick={() => onPin(id)}
              aria-pressed={pinnedLag === id}
            >
              <span className="font-mono text-[0.62rem] uppercase tracking-[0.14em] text-white/36">
                {lag.lag}일 전
              </span>
              <span
                className={`mt-2 block h-2 rounded-full border ${
                  lag.optimalLag ? "border-white/75" : "border-transparent"
                }`}
                style={{
                  background: lag.significant
                    ? "var(--accent-primary)"
                    : "rgba(255,255,255,0.18)",
                  boxShadow: lag.significant ? "0 0 18px rgba(0,255,255,0.28)" : "none",
                  width: `${Math.max(16, pct)}%`,
                }}
              />
              <span className="mt-2 block font-mono text-[0.64rem] text-white/44">
                {formatAdjustedPValue(lag.pvalueAdjusted)}
              </span>
              {active && <LagTooltip result={lag} group={group} />}
            </button>
          );
        })}
      </div>
    </article>
  );
}

function LagTooltip({ result, group }: { result: GrangerResult; group: RowGroup }) {
  return (
    <div className="pointer-events-none absolute left-0 top-[calc(100%+8px)] z-30 min-w-[240px] rounded-xl border border-white/12 bg-[#050505]/95 p-3 shadow-2xl">
      <p className="font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/34">
        {group.label} · {formatLag(result.lag)}
      </p>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
        <TooltipRow label="원래 p-value" value={fmtP(result.pvalue)} />
        <TooltipRow label="보정 p-value" value={fmtP(result.pvalueAdjusted)} highlight={result.significant} />
        <TooltipRow label="표시 강도" value={negLog10(result.pvalueAdjusted).toFixed(2)} />
        <TooltipRow label="판정" value={result.significant ? "의미 있음" : "약함"} highlight={result.significant} />
      </div>
      <p className="mt-2 border-t border-white/8 pt-2 text-[0.68rem] leading-5 text-white/32">
        {formatLag(result.lag)} 값으로 오늘의 변화를 설명해 본 결과입니다.
        {result.optimalLag ? " 이 관계에서 가장 설명력이 좋은 간격입니다." : ""}
      </p>
    </div>
  );
}

function TooltipRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <>
      <span className="font-mono text-[0.62rem] text-white/34">{label}</span>
      <span
        className={`font-mono text-[0.68rem] tabular-nums ${
          highlight ? "text-[var(--accent-primary)]" : "text-white/72"
        }`}
      >
        {value}
      </span>
    </>
  );
}
