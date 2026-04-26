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

        <div className="mx-auto w-full max-w-6xl space-y-14 px-6 py-14">
          {/* § PIPELINE HEALTH */}
          <section>
            <SectionHeader
              index="01"
              title="Pipeline Health"
              badge="run · coverage · source · raw metadata"
              description="Data integrity check before reading any signal. Quality precedes interpretation."
            />
            <div className="mt-8">
              <AnalysisOverviewDeck artifact={artifact} />
            </div>
          </section>

          {/* § DATA QUALITY */}
          <section>
            <SectionHeader
              index="02"
              title="Data Quality"
              badge="source lineage · ffill · exclusion"
              description="Where BTC, ETF, futures, and VIX inputs originated and how much interpolation was applied. High ffill counts indicate stale propagation, not real signal."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <DataQualityMatrix
                dataQuality={artifact.dataQuality}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

          {/* § GRANGER CAUSALITY */}
          <section>
            <SectionHeader
              index="03"
              title="Granger Causality"
              badge={`${artifact.granger.correction.nTests} relationships · lag 1–3d`}
              description="Tests whether past values of one series statistically precede changes in another. Highlighted results survive multiple-comparison correction."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <GrangerSymmetric granger={artifact.granger} />
            </div>
          </section>

          {/* § ALPHA VALIDATION */}
          <section>
            <SectionHeader
              index="04"
              title="Alpha Validation"
              badge="1d · 3d · 7d horizon · baseline uplift"
              description="Candidate signals must outperform naive baselines on lag-only forward returns. Walk-forward stability separates persistent edge from in-sample curve-fitting."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <AlphaValidationBoard
                alpha={artifact.alpha}
                summary={artifact.summary}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

          {/* § TARGET DIAGNOSTICS */}
          <section>
            <SectionHeader
              index="05"
              title="Target Diagnostics"
              badge="forward returns · fixed label · volatility adjusted label"
              description="Event rates for large-move labels. Labels that are too frequent or too rare distort the prediction task — compare fixed vs. vol-adjusted thresholds across regimes."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <TargetDiagnosticsPanel
                targets={artifact.targets}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

          {/* § PCA FACTOR ANALYSIS */}
          <section>
            <SectionHeader
              index="06"
              title="PCA Factor Analysis"
              badge="extended features · core features · loadings"
              description="Compression of market indicators into a single hybrid index. Loadings reveal which features drive the composite signal direction and magnitude."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <PcaTabs pca={artifact.pca} />
            </div>
          </section>

          {/* § STATIONARITY GATE */}
          <section>
            <SectionHeader
              index="07"
              title="Stationarity Gate"
              badge="ADF · stationarity · diagnostics"
              description="Granger tests assume stationary inputs. Weak ADF results cause skips or reduce confidence in causality estimates — this panel traces the root cause."
            />
            <div className="analysis-depth-panel mt-8 p-5 md:p-8">
              <StationarityPanel
                adf={artifact.stationarity?.adf}
                diagnosticsReady={diagnosticsReady}
              />
            </div>
          </section>

          {/* § RAW PARQUET METADATA */}
          <section>
            <SectionHeader
              index="08"
              title="Raw Parquet Metadata"
              badge="sentiment_join_stats · no-loss view"
              description="Full parquet metadata exposed as JSON. Dashboard cards are curated views — this section is the ground truth for debugging and contract verification."
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
  index,
  title,
  badge,
  description,
}: {
  index: string;
  title: string;
  badge: string;
  description: string;
}) {
  return (
    <div className="border-b border-white/8 pb-5">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="font-mono text-[0.62rem] tabular-nums tracking-[0.12em] text-white/20">
          §{index}
        </span>
        <h2 className="text-[1rem] font-semibold tracking-[-0.02em] text-white/90">{title}</h2>
        <span className="font-mono text-[0.65rem] tracking-[0.06em] text-[var(--accent-primary)]/50">
          {badge}
        </span>
      </div>
      <p className="mt-2 max-w-3xl font-mono text-[0.74rem] leading-6 text-white/36">{description}</p>
    </div>
  );
}
