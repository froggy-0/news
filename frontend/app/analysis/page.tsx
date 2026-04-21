import type { Metadata } from "next";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { AnalysisMasthead } from "@/components/analysis/AnalysisMasthead";
import { GrangerSymmetric } from "@/components/analysis/GrangerSymmetric";
import { PcaTabs } from "@/components/analysis/PcaTabs";
import { AnalysisUnavailable } from "@/components/analysis/AnalysisUnavailable";
import { AnalysisSignalField } from "@/components/analysis/AnalysisSignalField";
import { fetchSentimentInsight, isStaleReferenceDate } from "@/lib/analysis";
import { deriveAnalysisSummary } from "@/lib/analysis-derive";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "감성-시장 흐름 — SOVEREIGN BRIEF",
  description: "뉴스 감성과 시장 지표의 시간 순서 기반 관계 분석",
};

export default async function AnalysisPage() {
  let content: React.ReactNode;

  try {
    const artifact = await fetchSentimentInsight();
    const staleWarning = isStaleReferenceDate(artifact.referenceDate);
    const summary = deriveAnalysisSummary(artifact);

    content = (
      <>
        <AnalysisSignalField
          seedInput={`${artifact.runId}:${artifact.referenceDate}`}
          significantCount={summary.significantCount}
          topLoading={summary.topPcaDriver?.loading ?? 0}
          qualityStatus={summary.qualityStatus}
        />
        <AnalysisMasthead
          referenceDate={artifact.referenceDate}
          generatedAtUtc={artifact.generatedAtUtc}
          correction={artifact.granger.correction}
          staleWarning={staleWarning}
          summary={summary}
        />

        <div className="mx-auto w-full max-w-6xl space-y-16 px-6 py-14">
          {/* Granger */}
          <section>
            <SectionHeader
              title="누가 먼저 움직였나"
              badge={`${artifact.granger.correction.nTests}개 관계 · 1-3일 전 데이터 검정`}
              plain="뉴스 분위기가 시장을 먼저 움직였는지, 시장 움직임이 뉴스 분위기를 먼저 바꿨는지 봅니다."
              detail="밝은 표시는 여러 관계를 동시에 검정한 뒤에도 우연일 가능성이 낮은 결과입니다. 링은 같은 관계 안에서 가장 설명력이 좋았던 날짜 간격입니다."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <GrangerSymmetric granger={artifact.granger} />
            </div>
          </section>

          {/* PCA */}
          <section>
            <SectionHeader
              title="종합 신호를 만든 지표들"
              badge="확장 지표 · 핵심 지표 · 기여도"
              plain="여러 시장 지표를 하나의 종합 신호로 압축했을 때, 어떤 지표가 방향을 가장 많이 밀었는지 봅니다."
              detail="중앙선 오른쪽은 종합 신호를 올리는 방향, 왼쪽은 낮추는 방향입니다. 설명력이 높을수록 여러 지표의 흐름을 하나의 신호로 잘 요약했다는 뜻입니다."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <PcaTabs pca={artifact.pca} />
            </div>
          </section>
        </div>
      </>
    );
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    content = <AnalysisUnavailable reason={reason} />;
  }

  return (
    <main className="relative overflow-hidden pb-16">
      <SiteHeader historyEntries={[]} />
      {content}
    </main>
  );
}

function SectionHeader({
  title,
  badge,
  plain,
  detail,
}: {
  title: string;
  badge: string;
  plain: string;
  detail: string;
}) {
  return (
    <div className="border-b border-white/8 pb-5">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-[1.1rem] font-semibold tracking-[-0.02em] text-white">{title}</h2>
        <span className="font-mono text-[0.68rem] tracking-[0.04em] text-[var(--text-muted)]">
          {badge}
        </span>
      </div>
      {/* 비전문가용 한 줄 설명 */}
      <p className="mt-2 text-[0.9rem] leading-7 text-[var(--text-secondary)]">{plain}</p>
      {/* 상세 해석 가이드 */}
      <p className="mt-1.5 max-w-3xl text-[0.78rem] leading-6 text-[var(--text-muted)]">
        {detail}
      </p>
    </div>
  );
}
