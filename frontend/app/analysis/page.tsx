import type { Metadata } from "next";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { AnalysisMasthead } from "@/components/analysis/AnalysisMasthead";
import { GrangerSymmetric } from "@/components/analysis/GrangerSymmetric";
import { PcaTabs } from "@/components/analysis/PcaTabs";
import { AnalysisUnavailable } from "@/components/analysis/AnalysisUnavailable";
import { fetchSentimentInsight, isStaleReferenceDate } from "@/lib/analysis";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Sentiment Insight — SOVEREIGN BRIEF",
  description: "Granger 인과 검정과 PCA 로딩 기반 감성–시장 연관 분석",
};

export default async function AnalysisPage() {
  let content: React.ReactNode;

  try {
    const artifact = await fetchSentimentInsight();
    const staleWarning = isStaleReferenceDate(artifact.referenceDate);

    content = (
      <>
        <AnalysisMasthead
          referenceDate={artifact.referenceDate}
          generatedAtUtc={artifact.generatedAtUtc}
          correction={artifact.granger.correction}
          staleWarning={staleWarning}
        />

        <div className="mx-auto w-full max-w-6xl space-y-16 px-6 py-14">
          {/* Granger */}
          <section>
            <SectionHeader
              title="Granger 인과성 검정"
              badge={`${artifact.granger.correction.nTests}쌍 × lag 1-3 · FDR-BH 보정`}
              plain="한 변수의 과거 값이 다른 변수의 미래를 예측하는지 통계적으로 검사합니다."
              detail={`"forward"는 감성이 시장 지표를 앞서는 방향, "reverse"는 시장이 감성을 먼저 움직이는 방향입니다. 막대가 길수록 통계 신호가 강하며, 밝은 색(유의)은 p-value가 다중검정 보정 후에도 유의한 쌍입니다.`}
            />
            <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:p-8">
              <GrangerSymmetric granger={artifact.granger} />
            </div>
          </section>

          {/* PCA */}
          <section>
            <SectionHeader
              title="PCA 주성분 로딩"
              badge="FULL · CORE 피처셋 · PC1 기여도"
              plain="여러 시장 지표를 하나의 '종합 신호'로 압축할 때 각 지표가 얼마나 기여하는지 보여줍니다."
              detail={`양수(+) 막대는 지표가 신호 상승 방향에 기여, 음수(-) 막대는 반대 방향입니다. FULL은 모든 피처를, CORE는 다중공선성(VIF)을 제거한 핵심 피처만 사용합니다. 설명분산이 높을수록 압축이 잘 된 것입니다.`}
            />
            <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:p-8">
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
    <main className="pb-16">
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
