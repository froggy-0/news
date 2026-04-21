"use client";

import { useState } from "react";

import type { PcaIndex, PcaSection } from "@schema/analysis.types";

type TabId = "full" | "core";

export function PcaTabs({ pca }: { pca: PcaSection }) {
  const [active, setActive] = useState<TabId>("full");
  const data = pca[active];

  return (
    <div>
      {/* 탭 헤더 */}
      <div className="mb-6 flex items-end gap-0 border-b border-white/10">
        {(["full", "core"] as TabId[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActive(tab)}
            className={`relative px-5 pb-3 font-mono text-[0.72rem] uppercase tracking-[0.18em] transition-colors ${
              active === tab ? "text-white" : "text-white/32 hover:text-white/60"
            }`}
          >
            {tab}
            <span
              className="absolute inset-x-0 bottom-0 h-px origin-left bg-[var(--accent-primary)] transition-transform duration-300"
              style={{ transform: active === tab ? "scaleX(1)" : "scaleX(0)" }}
            />
          </button>
        ))}
      </div>

      {data.status !== "ok" ? (
        <EmptyState status={data.status} />
      ) : (
        <>
          <p className="mb-5 max-w-2xl text-[0.78rem] leading-6 text-white/35">
            <span className="text-white/50">읽는 법: </span>
            오른쪽으로 뻗은 막대(+)는 이 지표가 높을수록 종합 신호가 올라가는 관계,
            왼쪽(−)은 반대입니다. 막대가 길수록 이 지표가 신호에 더 많이 기여합니다.
            막대에 마우스를 올리면 정확한 수치를 확인할 수 있습니다.
          </p>
          <PcaIndexView data={data} />
        </>
      )}
    </div>
  );
}

function PcaIndexView({ data }: { data: PcaIndex }) {
  const [showReasons, setShowReasons] = useState(false);
  const [hoveredFeature, setHoveredFeature] = useState<string | null>(null);

  const entries = Object.entries(data.loadings).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 0.001);
  const totalAbsSum = entries.reduce((acc, [, v]) => acc + Math.abs(v), 0);

  return (
    <div className="space-y-6">
      {/* 메타 pills */}
      <div className="flex flex-wrap gap-2">
        <MetaPill label="PC" value={`${data.nComponents}`} />
        <MetaPill label="설명분산" value={`${(data.explainedVariance * 100).toFixed(1)}%`} />
        <MetaPill label="커버리지" value={`${(data.coverageRatio * 100).toFixed(1)}%`} />
        <QualityPill
          status={data.qualityStatus}
          reasons={data.qualityReasons}
          showReasons={showReasons}
          onToggle={() => setShowReasons((v) => !v)}
        />
      </div>

      {/* qualityReasons expand */}
      {showReasons && data.qualityReasons.length > 0 && (
        <div className="rounded-xl border border-[var(--accent-warning)]/20 bg-[var(--accent-warning)]/5 p-4">
          <ul className="space-y-1">
            {data.qualityReasons.map((r, i) => (
              <li key={i} className="font-mono text-[0.72rem] text-[var(--accent-warning)]/80">
                — {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 로딩 막대 차트 */}
      <div className="space-y-2.5">
        {entries.map(([feature, loading], i) => {
          const pct = (Math.abs(loading) / maxAbs) * 100;
          const absSharePct = totalAbsSum > 0 ? (Math.abs(loading) / totalAbsSum) * 100 : 0;
          const isPos = loading >= 0;
          const delayMs = i * 50;
          const shortName = feature.replace(/_lag\d+$/, "").replace(/_/g, " ");
          const isHovered = hoveredFeature === feature;

          return (
            <div
              key={feature}
              className="group relative flex items-center gap-3"
              onMouseEnter={() => setHoveredFeature(feature)}
              onMouseLeave={() => setHoveredFeature(null)}
            >
              {/* Feature label */}
              <span
                className={`w-[160px] shrink-0 font-mono text-[0.65rem] leading-tight tracking-[0.03em] transition-colors ${
                  isHovered ? "text-white/90" : "text-white/55"
                }`}
              >
                {shortName}
              </span>

              {/* Bi-directional bar */}
              <div className="relative flex h-[8px] flex-1 items-center">
                <div className="absolute left-1/2 h-full w-px -translate-x-1/2 bg-white/15" />
                <div
                  className="absolute h-full rounded-full transition-opacity duration-150"
                  style={{
                    width: `${pct / 2}%`,
                    ...(isPos
                      ? { left: "50%", background: isHovered ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.72)" }
                      : { right: "50%", background: isHovered ? "rgba(255,255,255,0.55)" : "rgba(255,255,255,0.32)" }),
                    transformOrigin: isPos ? "left" : "right",
                    animation: `barReveal 0.4s ease-out ${delayMs}ms both`,
                  }}
                />
              </div>

              {/* Loading value — 항상 표시 */}
              <span
                className={`w-[52px] shrink-0 text-right font-mono text-[0.68rem] tabular-nums transition-colors ${
                  isHovered ? (isPos ? "text-white" : "text-white/60") : isPos ? "text-white/70" : "text-white/40"
                }`}
              >
                {loading >= 0 ? "+" : ""}
                {loading.toFixed(3)}
              </span>

              {/* 호버 툴팁 */}
              {isHovered && (
                <div className="pointer-events-none absolute left-[170px] top-[calc(100%+6px)] z-20 min-w-[220px] rounded-lg border border-white/12 bg-[#0a0a0a]/95 px-3 py-2.5 shadow-xl">
                  <p className="mb-2 font-mono text-[0.62rem] uppercase tracking-[0.1em] text-white/30">
                    {shortName}
                  </p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                    <TipRow label="로딩값" value={(loading >= 0 ? "+" : "") + loading.toFixed(4)} highlight={isPos} hint="PC1에 대한 기여 방향과 크기" />
                    <TipRow label="|로딩|" value={Math.abs(loading).toFixed(4)} hint="절댓값 — 방향 무시한 영향력" />
                    <TipRow label="기여 비중" value={`${absSharePct.toFixed(1)}%`} hint="전체 피처 중 이 변수의 비율" />
                    <TipRow label="정규화 막대" value={`${pct.toFixed(1)}%`} hint="최대 로딩 대비 상대적 크기" />
                    <TipRow label="방향" value={isPos ? "양(+): 상승 기여" : "음(−): 하락 기여"} highlight={isPos} />
                    <TipRow label="순위" value={`#${i + 1} / ${entries.length}`} hint="절댓값 기준 영향력 순위" />
                  </div>
                  <p className="mt-2 border-t border-white/8 pt-1.5 font-mono text-[0.6rem] leading-relaxed text-white/25">
                    {isPos
                      ? "이 지표가 높을수록 종합 신호(PC1)가 상승하는 방향"
                      : "이 지표가 높을수록 종합 신호(PC1)가 낮아지는 방향"}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 제외된 피처 테이블 */}
      {data.excludedFeatures.length > 0 && (
        <div className="border-t border-white/8 pt-4">
          <p className="mb-2 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-white/28">
            VIF 제거 변수
          </p>
          <div className="space-y-1">
            {data.excludedFeatures.map((ef, i) => (
              <div key={i} className="flex items-baseline gap-3">
                <span className="font-mono text-[0.68rem] text-white/42">
                  {ef.feature.replace(/_/g, " ")}
                </span>
                {ef.reason && (
                  <span className="font-mono text-[0.62rem] text-[var(--accent-down)]/60">
                    {ef.reason}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TipRow({
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
          highlight ? "text-white/90" : "text-white/70"
        }`}
      >
        {value}
      </span>
    </>
  );
}

function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1">
      <span className="font-mono text-[0.62rem] uppercase tracking-[0.12em] text-white/32">
        {label}
      </span>
      <span className="font-mono text-[0.72rem] text-white/70">{value}</span>
    </div>
  );
}

function QualityPill({
  status,
  reasons,
  showReasons,
  onToggle,
}: {
  status: string;
  reasons: string[];
  showReasons: boolean;
  onToggle: () => void;
}) {
  const isDegraded = status === "degraded";
  const isCritical = status === "critical";
  const color = isCritical
    ? "var(--accent-down)"
    : isDegraded
      ? "var(--accent-warning)"
      : "var(--accent-green)";
  const hasReasons = reasons.length > 0 && (isDegraded || isCritical);

  return (
    <button
      type="button"
      onClick={hasReasons ? onToggle : undefined}
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] transition-colors ${
        hasReasons ? "cursor-pointer hover:bg-white/5" : "cursor-default"
      }`}
      style={{ borderColor: `color-mix(in srgb, ${color} 30%, transparent)` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      <span style={{ color }}>{status}</span>
      {hasReasons && <span className="text-white/28">{showReasons ? "▲" : "▼"}</span>}
    </button>
  );
}

function EmptyState({ status }: { status: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14">
      <p className="font-mono text-[0.7rem] uppercase tracking-[0.14em] text-[var(--text-muted)]">
        PCA 미수행
      </p>
      <p className="font-mono text-[0.65rem] text-white/28">status: {status}</p>
    </div>
  );
}
