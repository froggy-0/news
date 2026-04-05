import React from "react";

import { displayHeadline, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

export function JudgmentBlock({
  headline,
  summaryLead,
  summarySupport,
  issueDate,
}: {
  headline: string;
  summaryLead: string;
  summarySupport: string | null;
  issueDate: string;
}) {
  const cleanHeadline = hasUsableHeadline(headline)
    ? displayHeadline(headline)
    : `${formatPublicationDate(issueDate)} 발행본`;
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
    <section id="brief" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto w-full max-w-6xl space-y-12">
        <div className="space-y-6">
          <div className="relative pl-6 md:pl-10 max-w-4xl">
            <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-[#00ff66] via-[#00ff66]/40 to-transparent" />
            <div className="absolute left-0 top-0 h-px w-4 bg-[#00ff66]" />
            <div className="space-y-4">
              <h2 className="text-[9px] font-mono uppercase tracking-[0.38em] text-[#00ff66]/80">
                브리프 헤드라인
              </h2>
              <p className="text-base leading-8 text-white/88 md:text-lg md:leading-9">{cleanHeadline}</p>
            </div>
          </div>
        </div>

        <div className="space-y-8 max-w-4xl">
          {cleanLead ? (
            <div className="relative pl-6 md:pl-10">
              <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-[#00ff66] via-[#00ff66]/40 to-transparent" />
              <div className="absolute left-0 top-0 h-px w-4 bg-[#00ff66]" />
              <div className="space-y-4">
                <h3 className="text-[9px] font-mono uppercase tracking-[0.38em] text-[#00ff66]/80">
                  핵심 인사이트
                </h3>
                <p className="text-sm leading-8 text-white/90 md:text-base">{cleanLead}</p>
              </div>
            </div>
          ) : null}

          {cleanSupport ? (
            <div className="relative pl-6 md:pl-10">
              <div className="absolute left-0 top-0 h-full w-px bg-white/12" />
              <div className="space-y-4">
                <h3 className="text-[9px] font-mono uppercase tracking-[0.38em] text-white/34">
                  상세 맥락
                </h3>
                <p className="text-sm leading-8 text-white/62">{cleanSupport}</p>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
