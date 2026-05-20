import type { Metadata } from "next";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { AnalysisMasthead } from "@/components/analysis/AnalysisMasthead";
import { AnalysisUnavailable } from "@/components/analysis/AnalysisUnavailable";
import { AnalysisSignalField } from "@/components/analysis/AnalysisSignalField";
import { InsightHub } from "@/components/analysis/InsightHub";
import { fetchSentimentInsight, isStaleReferenceDate } from "@/lib/analysis";
import { deriveAnalysisSummary, isFullDiagnosticArtifact } from "@/lib/analysis-derive";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Signal Intelligence Lab — SOVEREIGN BRIEF",
  description: "Temporal precedence analysis of news sentiment and BTC market structure",
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
        <InsightHub artifact={artifact} diagnosticsReady={diagnosticsReady} />
      </>
    );
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    content = <AnalysisUnavailable reason={reason} />;
  }

  return (
    <main className="relative overflow-hidden pb-16">
      <SiteHeader />
      {content}
    </main>
  );
}

