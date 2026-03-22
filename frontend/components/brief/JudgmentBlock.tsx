import { Reveal } from "@/components/ui/Reveal";
import { displayHeadline, formatIssueDate, formatIssueTime, hasUsableHeadline } from "@/lib/format";

export function JudgmentBlock({
  headline,
  summaryLead,
  summarySupport,
  generatedAt,
}: {
  headline: string;
  summaryLead: string;
  summarySupport: string | null;
  generatedAt: string;
}) {
  const cleanHeadline = hasUsableHeadline(headline)
    ? displayHeadline(headline)
    : `${formatIssueDate(generatedAt)} 발행본`;
  const cleanLead =
    hasUsableHeadline(summaryLead) && displayHeadline(summaryLead) !== cleanHeadline
      ? displayHeadline(summaryLead)
      : null;
  const cleanSupport =
    summarySupport &&
    hasUsableHeadline(summarySupport) &&
    displayHeadline(summarySupport) !== cleanHeadline &&
    displayHeadline(summarySupport) !== cleanLead
      ? displayHeadline(summarySupport)
      : null;

  return (
    <Reveal className="hero-judgment-shell">
      <div className="hero-judgment-grid">
        <div className="space-y-6">
          <div className="space-y-3">
            <p className="section-title">오늘의 판단</p>
            <h2 className="display-headline display-headline-sm">{cleanHeadline}</h2>
          </div>
          {cleanLead ? <p className="hero-summary-copy">{cleanLead}</p> : null}
          {cleanSupport ? <p className="hero-support-note">{cleanSupport}</p> : null}
        </div>

        <div className="posture-shell">
          <div className="posture-header">
            <span className="posture-led" />
            <p className="section-title">발행 메타</p>
          </div>
          <div className="space-y-4">
            <div className="posture-row">
              <span className="posture-label">발행</span>
              <span className="posture-value">{formatIssueTime(generatedAt)} KST</span>
            </div>
            {cleanSupport ? (
              <>
                <div className="posture-divider" />
                <p className="copy-block text-sm leading-7 text-[var(--text-secondary)]">{cleanSupport}</p>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </Reveal>
  );
}
