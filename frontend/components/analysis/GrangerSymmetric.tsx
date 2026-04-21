"use client";

import { useState, useMemo } from "react";

import type { GrangerResult, GrangerSection } from "@schema/analysis.types";

type GroupKey = string;

function groupKey(r: GrangerResult): GroupKey {
  return `${r.predictor}||${r.target}||${r.direction}`;
}

function formatLabel(predictor: string, target: string): string {
  const shorten = (s: string) =>
    s.replace(/_lag\d+$/, "").replace(/_mean$/, "").replace(/_/g, " ");
  return `${shorten(predictor)} → ${shorten(target)}`;
}

function negLog10(p: number | null): number {
  if (p === null || p <= 0) return 0;
  return -Math.log10(Math.min(p, 1));
}

function fmtP(v: number | null): string {
  if (v === null) return "—";
  if (v < 0.001) return "<0.001";
  return v.toFixed(3);
}

type RowGroup = {
  key: GroupKey;
  predictor: string;
  target: string;
  direction: "forward" | "reverse";
  label: string;
  optimal: GrangerResult;
  allLags: GrangerResult[];
};

export function GrangerSymmetric({ granger }: { granger: GrangerSection }) {
  const [expanded, setExpanded] = useState<GroupKey | null>(null);
  // 각 lag 행에 대한 호버 상태: "groupKey|lag"
  const [hoveredLag, setHoveredLag] = useState<string | null>(null);

  const groups: RowGroup[] = useMemo(() => {
    const map = new Map<GroupKey, GrangerResult[]>();
    for (const r of granger.results) {
      const k = groupKey(r);
      const arr = map.get(k) ?? [];
      arr.push(r);
      map.set(k, arr);
    }
    const rows: RowGroup[] = [];
    for (const [k, lags] of map.entries()) {
      const sorted = [...lags].sort((a, b) => a.lag - b.lag);
      const optimal = sorted.find((r) => r.optimalLag) ?? sorted[0];
      rows.push({
        key: k,
        predictor: optimal.predictor,
        target: optimal.target,
        direction: optimal.direction,
        label: formatLabel(optimal.predictor, optimal.target),
        optimal,
        allLags: sorted,
      });
    }
    return rows.sort((a, b) => {
      if (a.direction !== b.direction) return a.direction === "forward" ? -1 : 1;
      return (a.optimal.pvalueAdjusted ?? 1) - (b.optimal.pvalueAdjusted ?? 1);
    });
  }, [granger.results]);

  const maxScore = useMemo(() => {
    const all = granger.results.map((r) => negLog10(r.pvalueAdjusted));
    all.sort((a, b) => a - b);
    return all[Math.floor(all.length * 0.95)] || 1;
  }, [granger.results]);

  const forward = groups.filter((g) => g.direction === "forward");
  const reverse = groups.filter((g) => g.direction === "reverse");
  const maxRows = Math.max(forward.length, reverse.length);

  if (!granger.executed) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="font-mono text-[0.8rem] tracking-[0.08em] text-[var(--text-muted)]">
          Granger 검정 미수행
        </p>
      </div>
    );
  }

  const rowsToShow = (g: RowGroup) =>
    expanded === g.key ? g.allLags : [g.optimal];

  return (
    <div className="relative">
      {/* 주의 문구 */}
      <div className="absolute right-0 top-0 hidden md:block">
        <p className="font-mono text-[0.65rem] tracking-[0.06em] text-white/28">
          Granger causality ≠ causation
        </p>
      </div>

      {/* 헤더 */}
      <div className="mb-4 grid grid-cols-[1fr_2px_1fr] items-center gap-0">
        <p className="pr-4 text-right font-mono text-[0.7rem] uppercase tracking-[0.14em] text-[var(--text-muted)]">
          forward
          <span className="ml-2 text-white/28">감성 → 시장</span>
        </p>
        <div />
        <p className="pl-4 font-mono text-[0.7rem] uppercase tracking-[0.14em] text-[var(--text-muted)]">
          reverse
          <span className="ml-2 text-white/28">시장 → 감성</span>
        </p>
      </div>

      {/* 중앙축 + 행 */}
      <div className="relative">
        <div
          className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-white/20"
          style={{ transformOrigin: "top center", animation: "axisDraw 0.6s ease-out forwards" }}
        />

        <style>{`
          @keyframes axisDraw {
            from { transform: translateX(-50%) scaleY(0); }
            to   { transform: translateX(-50%) scaleY(1); }
          }
          @keyframes barReveal {
            from { transform: scaleX(0); opacity: 0; }
            to   { transform: scaleX(1); opacity: 1; }
          }
        `}</style>

        {Array.from({ length: maxRows }).map((_, rowIdx) => {
          const fwdGroup = forward[rowIdx];
          const revGroup = reverse[rowIdx];
          const isExpFwd = fwdGroup && expanded === fwdGroup.key;
          const isExpRev = revGroup && expanded === revGroup.key;
          const dimmed = expanded !== null;

          return (
            <div key={rowIdx} className="grid grid-cols-[1fr_2px_1fr] items-start gap-0">
              <div className={`py-1 pr-3 transition-opacity duration-200 ${dimmed && !isExpFwd ? "opacity-35" : "opacity-100"}`}>
                {fwdGroup ? (
                  <BarSide
                    group={fwdGroup}
                    rows={rowsToShow(fwdGroup)}
                    maxScore={maxScore}
                    align="right"
                    rowIndex={rowIdx}
                    onClick={() => setExpanded(isExpFwd ? null : fwdGroup.key)}
                    expanded={!!isExpFwd}
                    hoveredLag={hoveredLag}
                    onHoverLag={setHoveredLag}
                  />
                ) : (
                  <div className="h-8" />
                )}
              </div>

              <div />

              <div className={`py-1 pl-3 transition-opacity duration-200 ${dimmed && !isExpRev ? "opacity-35" : "opacity-100"}`}>
                {revGroup ? (
                  <BarSide
                    group={revGroup}
                    rows={rowsToShow(revGroup)}
                    maxScore={maxScore}
                    align="left"
                    rowIndex={rowIdx}
                    onClick={() => setExpanded(isExpRev ? null : revGroup.key)}
                    expanded={!!isExpRev}
                    hoveredLag={hoveredLag}
                    onHoverLag={setHoveredLag}
                  />
                ) : (
                  <div className="h-8" />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 범례 + 읽는 법 */}
      <div className="mt-6 space-y-3 border-t border-white/8 pt-4">
        <div className="flex flex-wrap items-center gap-5">
          <LegendDot color="var(--accent-primary)" label="유의 (q<0.05)" />
          <LegendDot color="rgba(255,255,255,0.18)" label="비유의" />
          <span className="font-mono text-[0.65rem] text-white/28">
            행 클릭 → lag 1/2/3 펼침 · 막대 호버 → p/q 수치
          </span>
        </div>
        <p className="max-w-2xl text-[0.75rem] leading-6 text-white/30">
          <span className="text-white/45">읽는 법: </span>
          왼쪽(forward)은 감성 지표가 시장을 며칠 앞서 예측하는 관계, 오른쪽(reverse)은 반대입니다.
          막대가 밝을수록 통계적으로 의미 있는 신호이며, lag는 며칠 전 데이터를 사용했는지를 나타냅니다.
          인과성 검정은 상관관계와 다르게 시간 순서를 고려하므로 더 신뢰할 수 있습니다.
        </p>
      </div>
    </div>
  );
}

function BarSide({
  group,
  rows,
  maxScore,
  align,
  rowIndex,
  onClick,
  expanded,
  hoveredLag,
  onHoverLag,
}: {
  group: RowGroup;
  rows: GrangerResult[];
  maxScore: number;
  align: "left" | "right";
  rowIndex: number;
  onClick: () => void;
  expanded: boolean;
  hoveredLag: string | null;
  onHoverLag: (key: string | null) => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full cursor-pointer rounded-lg py-1 text-left transition-colors hover:bg-white/[0.03]"
      aria-expanded={expanded}
    >
      {rows.map((r, i) => {
        const score = negLog10(r.pvalueAdjusted);
        const pct = Math.min((score / maxScore) * 100, 100);
        const isOptimal = r.optimalLag;
        const isSig = r.significant;
        const delayMs = rowIndex * 60 + i * 30;
        const lagId = `${group.key}|${r.lag}`;
        const isHovered = hoveredLag === lagId;

        return (
          <div
            key={r.lag}
            className="relative mb-1 flex items-center gap-2"
            style={{ flexDirection: align === "right" ? "row-reverse" : "row" }}
            onMouseEnter={() => onHoverLag(lagId)}
            onMouseLeave={() => onHoverLag(null)}
          >
            {/* Label */}
            {i === 0 ? (
              <span
                className={`w-[90px] shrink-0 font-mono text-[0.65rem] leading-tight tracking-[0.03em] ${
                  isSig ? "text-white/80" : "text-white/32"
                } ${align === "right" ? "text-right" : "text-left"}`}
              >
                {group.label}
              </span>
            ) : (
              <span className="w-[90px] shrink-0" />
            )}

            {/* Lag pill */}
            <span className={`font-mono text-[0.6rem] transition-colors ${isOptimal ? "text-white/50" : "text-white/22"}`}>
              L{r.lag}
            </span>

            {/* Bar + 호버 툴팁 */}
            <div className="relative flex-1">
              <div
                className="relative h-[6px] overflow-hidden rounded-full bg-white/8"
                style={{ transformOrigin: align === "right" ? "right" : "left" }}
              >
                <div
                  className="absolute inset-y-0 rounded-full transition-opacity duration-150"
                  style={{
                    width: `${pct}%`,
                    background: isSig ? "var(--accent-primary)" : "rgba(255,255,255,0.18)",
                    opacity: isHovered ? 1 : isOptimal ? 0.85 : 0.45,
                    [align === "right" ? "right" : "left"]: 0,
                    transformOrigin: align === "right" ? "right" : "left",
                    animation: `barReveal 0.45s ease-out ${delayMs}ms both`,
                  }}
                />
              </div>

              {/* 호버 시 p/q 수치 툴팁 */}
              {isHovered && (
                <div
                  className="pointer-events-none absolute z-20 whitespace-nowrap rounded-lg border border-white/12 bg-[#0a0a0a]/95 px-3 py-2 shadow-xl"
                  style={{
                    top: "calc(100% + 6px)",
                    ...(align === "right" ? { right: 0 } : { left: 0 }),
                  }}
                >
                  <div className="mb-1 font-mono text-[0.62rem] uppercase tracking-[0.1em] text-white/30">
                    {group.label} · lag {r.lag}
                    {isOptimal && (
                      <span className="ml-1.5 text-[var(--accent-primary)]">optimal</span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                    <TooltipRow label="p-value" value={fmtP(r.pvalue)} hint="원시 유의확률" />
                    <TooltipRow
                      label="q (보정 후)"
                      value={fmtP(r.pvalueAdjusted)}
                      highlight={isSig}
                      hint="다중검정 보정값 — 이 기준으로 판단"
                    />
                    <TooltipRow label="−log₁₀(q)" value={score > 0 ? score.toFixed(2) : "—"} hint="막대 길이 기준 (클수록 강한 신호)" />
                    <TooltipRow
                      label="유의 (q<0.05)"
                      value={isSig ? "✓ yes" : "no"}
                      highlight={isSig}
                    />
                  </div>
                  <p className="mt-2 border-t border-white/8 pt-1.5 font-mono text-[0.6rem] leading-relaxed text-white/25">
                    lag {r.lag} = {r.lag}일 전 값으로 현재를 예측
                    {isOptimal ? " · 이 lag가 가장 강한 신호" : ""}
                  </p>
                </div>
              )}
            </div>

            {/* Significant dot */}
            {isSig && isOptimal && (
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent-primary)]"
                style={{ boxShadow: "0 0 6px rgba(0,255,255,0.6)" }}
              />
            )}
          </div>
        );
      })}
    </button>
  );
}

function TooltipRow({
  label,
  value,
  highlight,
  hint,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  hint?: string;
}) {
  return (
    <>
      <span className="font-mono text-[0.62rem] leading-tight text-white/36">
        {label}
        {hint && <span className="block text-[0.55rem] text-white/20">{hint}</span>}
      </span>
      <span
        className={`font-mono text-[0.68rem] tabular-nums ${
          highlight ? "text-[var(--accent-primary)]" : "text-white/80"
        }`}
      >
        {value}
      </span>
    </>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      <span className="font-mono text-[0.65rem] text-white/42">{label}</span>
    </div>
  );
}
