import { Reveal } from "@/components/ui/Reveal";
import { displayHeadline, formatIssueTime } from "@/lib/format";

function postureTone(headline: string): {
  posture: string;
  volatility: string;
  bias: string;
} {
  if (headline.includes("매수 관심")) {
    return {
      posture: "매수 관심",
      volatility: "선별적 위험 선호",
      bias: "공격적 선별 대응",
    };
  }
  if (headline.includes("리스크 주의")) {
    return {
      posture: "리스크 주의",
      volatility: "변동성 경계",
      bias: "방어적 접근",
    };
  }
  return {
    posture: "관망",
    volatility: "균형 구간",
    bias: "관망 우위",
  };
}

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
  const cleanHeadline = displayHeadline(headline);
  const tone = postureTone(cleanHeadline);

  return (
    <Reveal className="hero-judgment-shell">
      <div className="hero-judgment-grid">
        <div className="space-y-6">
          <div className="space-y-3">
            <p className="section-title">오늘의 판단</p>
            <h2 className="display-headline display-headline-sm">{cleanHeadline}</h2>
          </div>
          <p className="hero-summary-copy">{summaryLead}</p>
          {summarySupport ? <p className="hero-support-note">{summarySupport}</p> : null}
        </div>

        <div className="posture-shell">
          <div className="posture-header">
            <span className="posture-led" />
            <p className="section-title">시장 자세</p>
          </div>
          <div className="space-y-4">
            <div className="posture-row">
              <span className="posture-label">리스크</span>
              <span className="posture-value">{tone.posture}</span>
            </div>
            <div className="posture-row">
              <span className="posture-label">변동성</span>
              <span className="posture-value posture-muted">{tone.volatility}</span>
            </div>
            <div className="posture-row">
              <span className="posture-label">한국장</span>
              <span className="posture-value posture-muted">{tone.bias}</span>
            </div>
            <div className="posture-divider" />
            <p className="posture-meta">발행 · {formatIssueTime(generatedAt)} KST</p>
          </div>
        </div>
      </div>
    </Reveal>
  );
}
