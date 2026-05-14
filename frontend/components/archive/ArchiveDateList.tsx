import Link from "next/link";
import { ArrowRight, TrendingUp, TrendingDown, Minus } from "lucide-react";

import { displayHeadline, formatIssueTime, hasUsableHeadline } from "@/lib/format";

type ArchiveItem = {
  date: string;
  generatedAt?: string;
  quality?: "ok" | "degraded" | "critical";
  headline?: string;
  displayHeadline?: string;
  translationStatus?: "ok" | "partial" | "failed";
  newsAll?: number;
  xSignalAll?: number;
  sovereignScore?: number;
  sovereignZone?: "bull" | "neutral" | "bear";
  sovereignRegime?: string;
  sovereignLabelKo?: string;
};

const ZONE_CFG = {
  bull:    { color: "#10b981", bg: "rgba(16,185,129,0.08)",   border: "rgba(16,185,129,0.22)", label: "강세" },
  neutral: { color: "#94a3b8", bg: "rgba(100,116,139,0.08)", border: "rgba(100,116,139,0.22)", label: "중립" },
  bear:    { color: "#ef4444", bg: "rgba(239,68,68,0.08)",   border: "rgba(239,68,68,0.22)",  label: "약세" },
} as const;

const REGIME_COLORS: Record<string, string> = {
  BullQuiet:    "#10b981",
  BullHeated:   "#f0b90b",
  BearPanic:    "#ef4444",
  Choppy:       "#f0b90b",
  Transitional: "rgba(255,255,255,0.60)",
};

const REGIME_LABELS: Record<string, string> = {
  BullQuiet:    "안정 상승",
  BullHeated:   "과열 상승",
  BearPanic:    "공포 하락",
  Choppy:       "방향 불명",
  Transitional: "전환 구간",
};

function ZoneIcon({ zone }: { zone?: "bull" | "neutral" | "bear" }) {
  if (zone === "bull") return <TrendingUp className="h-3.5 w-3.5" />;
  if (zone === "bear") return <TrendingDown className="h-3.5 w-3.5" />;
  return <Minus className="h-3.5 w-3.5" />;
}

function ScoreBadge({ score, zone }: { score?: number; zone?: "bull" | "neutral" | "bear" }) {
  if (score == null) {
    return (
      <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-md border border-white/8 bg-white/[0.03]">
        <span className="font-mono text-[11px] text-white/22">N/A</span>
      </div>
    );
  }
  const cfg = ZONE_CFG[zone ?? "neutral"];
  return (
    <div
      className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-md border"
      style={{ borderColor: cfg.border, background: cfg.bg }}
    >
      <span className="font-mono text-[26px] font-bold leading-none tabular-nums" style={{ color: cfg.color }}>
        {Math.round(score)}
      </span>
      <span className="mt-0.5 font-mono text-[8px] uppercase tracking-[0.12em]" style={{ color: cfg.color, opacity: 0.7 }}>
        {cfg.label}
      </span>
    </div>
  );
}

function formatDate(dateStr: string): { month: string; day: string; dow: string } {
  const d = new Date(dateStr + "T00:00:00+09:00");
  const dows = ["일", "월", "화", "수", "목", "금", "토"];
  return {
    month: String(d.getMonth() + 1).padStart(2, "0"),
    day: String(d.getDate()).padStart(2, "0"),
    dow: dows[d.getDay()] ?? "",
  };
}

export function ArchiveDateList({ items }: { items: ArchiveItem[] }) {
  return (
    <section className="relative z-10 px-4 py-16 md:px-20 md:py-24">
      <div className="mx-auto w-full max-w-5xl">
        {/* Header */}
        <div className="mb-10 border-b border-white/[0.06] pb-8">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-[0.28em]" style={{ color: "#f0b90b" }}>
            Archive Index
          </p>
          <h1 className="text-[28px] font-bold leading-tight text-white/88 md:text-[40px]">
            날짜별 브리핑 기록
          </h1>
          <p className="mt-3 font-mono text-[12px] text-white/32">
            {items.length}개 발행본 · Sovereign Index 기준 정렬
          </p>
        </div>

        {/* Column headers */}
        <div className="mb-3 hidden grid-cols-[64px_1fr_auto] items-center gap-5 px-2 md:grid">
          <span className="font-mono text-[9px] uppercase tracking-[0.20em] text-white/22 text-center">INDEX</span>
          <span className="font-mono text-[9px] uppercase tracking-[0.20em] text-white/22">브리핑</span>
          <span className="font-mono text-[9px] uppercase tracking-[0.20em] text-white/22 pr-2">소스</span>
        </div>

        {/* Archive rows */}
        <div className="flex flex-col gap-2">
          {items.map((item) => {
            const { month, day, dow } = formatDate(item.date);
            const regimeColor = item.sovereignRegime ? (REGIME_COLORS[item.sovereignRegime] ?? "rgba(255,255,255,0.60)") : "rgba(255,255,255,0.40)";
            const regimeLabel = item.sovereignRegime ? (REGIME_LABELS[item.sovereignRegime] ?? item.sovereignRegime) : null;
            const headline = item.displayHeadline && hasUsableHeadline(item.displayHeadline)
              ? item.displayHeadline
              : item.headline && hasUsableHeadline(item.headline)
                ? displayHeadline(item.headline)
                : null;

            return (
              <Link
                key={item.date}
                href={`/archive/${item.date}`}
                className="group grid grid-cols-[64px_1fr] gap-4 rounded-lg border border-white/[0.06] bg-white/[0.02] p-4 transition-all duration-200 hover:border-[rgba(240,185,11,0.22)] hover:bg-white/[0.035] md:grid-cols-[64px_1fr_auto] md:items-center md:gap-5 md:px-5 md:py-4"
              >
                {/* Score badge */}
                <ScoreBadge score={item.sovereignScore} zone={item.sovereignZone} />

                {/* Content */}
                <div className="min-w-0 space-y-2">
                  {/* Date + regime row */}
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="font-mono text-[13px] font-semibold text-white/68">
                      {month}/{day}
                      <span className="ml-1.5 text-[10px] text-white/32">({dow})</span>
                    </span>
                    {item.generatedAt && (
                      <span className="font-mono text-[10px] text-white/22">
                        {formatIssueTime(item.generatedAt)} KST
                      </span>
                    )}
                    {regimeLabel && (
                      <span
                        className="flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.12em]"
                        style={{
                          color: regimeColor,
                          borderColor: `${regimeColor}30`,
                          background: `${regimeColor}10`,
                        }}
                      >
                        <ZoneIcon zone={item.sovereignZone} />
                        {regimeLabel}
                      </span>
                    )}
                  </div>

                  {/* Headline */}
                  <p className="line-clamp-2 text-[13px] leading-6 text-white/60 transition group-hover:text-white/82 md:text-[14px]">
                    {headline ?? `${item.date} 발행본`}
                  </p>
                </div>

                {/* Right: source counts + arrow */}
                <div className="col-span-2 flex items-center justify-between md:col-span-1 md:flex-col md:items-end md:gap-2">
                  {(item.newsAll ?? 0) > 0 || (item.xSignalAll ?? 0) > 0 ? (
                    <div className="flex gap-2">
                      {(item.newsAll ?? 0) > 0 && (
                        <span className="rounded border border-white/8 bg-white/[0.03] px-2 py-0.5 font-mono text-[9px] text-white/30">
                          뉴스 {item.newsAll}
                        </span>
                      )}
                      {(item.xSignalAll ?? 0) > 0 && (
                        <span className="rounded border border-white/8 bg-white/[0.03] px-2 py-0.5 font-mono text-[9px] text-white/30">
                          X {item.xSignalAll}
                        </span>
                      )}
                    </div>
                  ) : <div />}
                  <ArrowRight
                    className="h-4 w-4 text-white/20 transition-all group-hover:translate-x-1 group-hover:text-[rgba(240,185,11,0.70)]"
                    aria-hidden
                  />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}
