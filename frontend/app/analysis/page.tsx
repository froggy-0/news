import type { Metadata } from "next";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { AnalysisMasthead } from "@/components/analysis/AnalysisMasthead";
import { GrangerSymmetric } from "@/components/analysis/GrangerSymmetric";
import { PcaTabs } from "@/components/analysis/PcaTabs";
import { AnalysisUnavailable } from "@/components/analysis/AnalysisUnavailable";
import { AnalysisSignalField } from "@/components/analysis/AnalysisSignalField";
import {
  AlphaValidationBoard,
  AnalysisOverviewDeck,
  DataQualityMatrix,
  RawMetadataExplorer,
  StationarityPanel,
  TargetDiagnosticsPanel,
  isFullDiagnosticArtifact,
} from "@/components/analysis/AnalysisDashboardPanels";
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
    const diagnosticsReady = isFullDiagnosticArtifact(artifact);

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
          schemaVersion={artifact.schemaVersion}
          diagnosticsReady={diagnosticsReady}
        />

        <div className="mx-auto w-full max-w-6xl space-y-16 px-6 py-14">
          {/* Overview */}
          <section>
            <SectionHeader
              title="오늘 분석을 믿어도 되는가"
              badge="run · coverage · source · raw metadata"
              plain="가장 먼저 데이터 상태와 분석 실행 상태를 봅니다. 신호보다 품질이 먼저입니다."
              detail="상단 카드는 parquet metadata의 핵심 진단값을 압축한 것입니다. 마스킹, ffill, skip이 커지면 아래 통계 결과는 참고용으로 낮춰 읽어야 합니다."
            />
            <div className="mt-8">
              <AnalysisOverviewDeck artifact={artifact} />
            </div>
          </section>

          {/* Data quality */}
          <section>
            <SectionHeader
              title="입력 데이터 상태"
              badge="source lineage · ffill · exclusion"
              plain="BTC, ETF, 선물, VIX 같은 입력 데이터가 어디서 왔고 얼마나 보정되었는지 확인합니다."
              detail="ffill이 큰 지표는 신호처럼 보여도 실제로는 오래된 값이 유지된 것일 수 있습니다. source lineage와 함께 봐야 합니다."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <DataQualityMatrix
                dataQuality={artifact.dataQuality}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

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

          {/* Alpha */}
          <section>
            <SectionHeader
              title="신호가 기준선을 이겼나"
              badge="1d · 3d · 7d horizon · baseline uplift"
              plain="후보 신호가 단순 baseline보다 나은지, 그리고 그 성능이 walk-forward에서도 유지되는지 봅니다."
              detail="hit rate만 높아도 baseline 대비 uplift가 없거나 walk-forward 안정성이 낮으면 기본 후보로 승격하지 않는 것이 안전합니다."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <AlphaValidationBoard
                alpha={artifact.alpha}
                summary={artifact.summary}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

          {/* Targets */}
          <section>
            <SectionHeader
              title="예측 문제가 너무 쉬워 보이지 않는가"
              badge="forward returns · fixed label · volatility adjusted label"
              plain="large move target의 이벤트 비율을 확인해 label이 과도하게 흔하거나 희소하지 않은지 봅니다."
              detail="고정 임계값 label과 변동성 보정 label을 함께 보면 시장 regime에 따라 이벤트 정의가 왜곡되는지 점검할 수 있습니다."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <TargetDiagnosticsPanel
                targets={artifact.targets}
                diagnosticsReady={diagnosticsReady}
              />
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

          {/* Stationarity */}
          <section>
            <SectionHeader
              title="통계 검정 전제"
              badge="ADF · stationarity · diagnostics"
              plain="시계열 검정이 해석 가능한 조건에서 실행되었는지 확인합니다."
              detail="정상성 조건이 약하면 Granger 결과는 skip되거나 해석 신뢰도가 낮아질 수 있습니다. 이 표는 그 원인을 추적하기 위한 비행기록장치입니다."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <StationarityPanel
                adf={artifact.stationarity?.adf}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

          {/* Raw metadata */}
          <section>
            <SectionHeader
              title="원본 메타데이터"
              badge="sentiment_join_stats · no-loss view"
              plain="요약 화면에서 빠진 필드가 없도록 parquet metadata 원본을 접을 수 있는 JSON으로 제공합니다."
              detail="대시보드 카드는 해석을 돕기 위한 뷰이고, 이 영역은 디버깅과 원인 추적을 위한 원본 계약입니다."
            />
            <div className="mt-8">
              <RawMetadataExplorer
                rawStats={artifact.rawStats}
                diagnosticsReady={diagnosticsReady}
              />
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
