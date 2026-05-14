import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BriefBody, sanitizePublicBody } from "@/components/brief/BriefBody";
import { JudgmentBlock } from "@/components/brief/JudgmentBlock";
import { TopicGrid } from "@/components/brief/TopicGrid";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { CryptoPulseBoard } from "@/components/market/CryptoPulseBoard";
import { SourceFeed } from "@/components/feed/SourceFeed";
import { fetchBriefByDate, fetchIndex } from "@/lib/r2";
import type { RiskOverlay, SovereignIndex } from "@schema/brief.types";

/* ── 소버린 컴팩트 스트립 (메인페이지와 동일 스타일) ─────────────────────── */

const ZONE_COLOR = { bull: "#10b981", neutral: "#64748b", bear: "#ef4444" } as const;
const ZONE_LABEL = { bull: "강세 구간", neutral: "중립 구간", bear: "약세 구간" } as const;
const REGIME_COLOR: Record<string, string> = {
  BullQuiet: "#10b981", BullHeated: "#f0b90b",
  BearPanic: "#ef4444", Choppy: "#f0b90b", Transitional: "rgba(255,255,255,0.72)",
};
const REGIME_LABEL: Record<string, string> = {
  BullQuiet: "안정 상승", BullHeated: "과열 상승",
  BearPanic: "공포 하락", Choppy: "방향 불명", Transitional: "전환 구간",
};
const CONF_COLOR: Record<string, string> = {
  HIGH: "#10b981", MEDIUM: "#f0b90b", LOW: "rgba(255,255,255,0.48)",
};
const CONF_LABEL: Record<string, string> = {
  HIGH: "신호 강함", MEDIUM: "신호 보통", LOW: "신호 약함",
};

function SovereignStrip({
  sovereignIndex: si,
  riskOverlay: ro,
}: {
  sovereignIndex: SovereignIndex | null;
  riskOverlay: RiskOverlay | null;
}) {
  if (!si && !ro) return null;
  return (
    <div className="flex justify-center px-6 py-6 md:px-20">
      <div className="flex items-center gap-0 overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.03] backdrop-blur-sm">
        {si && (
          <div className="flex items-center gap-3 px-5 py-3">
            <div
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: ZONE_COLOR[si.zone], boxShadow: `0 0 6px ${ZONE_COLOR[si.zone]}80` }}
            />
            <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/32">Index</span>
            <span className="flex items-baseline gap-1">
              <span
                className="font-mono text-[18px] font-bold tabular-nums leading-none"
                style={{ color: ZONE_COLOR[si.zone] }}
              >
                {Math.round(si.score)}
              </span>
              {si.scoreDelta != null && (
                <span
                  className="font-mono text-[11px] font-semibold tabular-nums leading-none"
                  style={{ color: si.scoreDelta >= 0 ? "#10b981" : "#f87171" }}
                >
                  {si.scoreDelta >= 0 ? "↑" : "↓"}{Math.abs(Math.round(si.scoreDelta))}
                </span>
              )}
            </span>
            <span className="whitespace-nowrap font-mono text-[10px] text-white/38">
              {ZONE_LABEL[si.zone]}
            </span>
          </div>
        )}
        {si && ro && <div className="h-8 w-px bg-white/[0.08]" />}
        {ro && (
          <div className="flex items-center gap-3 px-5 py-3">
            <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/32">State</span>
            <span
              className="whitespace-nowrap text-[14px] font-bold leading-none"
              style={{ color: REGIME_COLOR[ro.regimeState] ?? "rgba(255,255,255,0.72)" }}
            >
              {REGIME_LABEL[ro.regimeState] ?? ro.regimeState}
            </span>
            {ro.signalConfidence && ro.signalConfidence !== "NONE" && CONF_COLOR[ro.signalConfidence] && (
              <>
                <div className="h-3 w-px bg-white/[0.08]" />
                <span
                  className="whitespace-nowrap font-mono text-[10px] font-semibold"
                  style={{ color: CONF_COLOR[ro.signalConfidence] }}
                >
                  {CONF_LABEL[ro.signalConfidence]}
                </span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export async function generateStaticParams() {
  const index = await fetchIndex();
  return index.dates.map((date) => ({ date }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ date: string }>;
}): Promise<Metadata> {
  const { date } = await params;
  const brief = await fetchBriefByDate(date);
  return {
    title: `${date} · SOVEREIGN BRIEF`,
    description: brief.meta.displayHeadline || brief.aiJudgment.headline,
  };
}

export default async function ArchiveDetailPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;

  try {
    const brief = await fetchBriefByDate(date);
    const publicBody = sanitizePublicBody(brief.aiJudgment.body);

    return (
      <main className="pb-6">
        <SiteHeader variant="archive-detail" />
        <SovereignStrip sovereignIndex={brief.sovereignIndex} riskOverlay={brief.riskOverlay} />
        <JudgmentBlock
          headline={brief.meta.displayHeadline || brief.aiJudgment.headline}
          summaryLead={brief.aiJudgment.summaryLead}
          summarySupport={brief.aiJudgment.summarySupport}
          issueDate={brief.meta.date}
        />
        <CryptoPulseBoard
          snapshot={brief.marketSnapshot}
          indicators={brief.cryptoIndicators}
          bitcoin={brief.bitcoin}
          etfHistory={brief.etfHistory}
        />
        <BriefBody body={publicBody} date={brief.meta.date} />
        <TopicGrid items={brief.topicSummaries} />
        <SourceFeed
          featuredNews={brief.featuredNews}
          allNews={brief.allNews}
          featuredXSignals={brief.featuredXSignals}
          allXSignals={brief.allXSignals}
          showRawTitle
          showRawToggle
        />
      </main>
    );
  } catch {
    notFound();
  }
}
