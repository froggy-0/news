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
    <section id="brief" className="relative z-10 border-b border-[#2b3139] px-6 py-16 md:px-20">
      <div className="mx-auto w-full space-y-10">
        <div className="space-y-6">
          <div className="relative pl-6 md:pl-10 max-w-4xl">
            <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-[#f0b90b] via-[rgba(240,185,11,0.3)] to-transparent" />
            <div className="absolute left-0 top-0 h-px w-4 bg-[#f0b90b]" />
            <div className="space-y-3">
              <h2
                className="text-[9px] uppercase tracking-[0.16em] text-[#f0b90b]"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                브리프 헤드라인
              </h2>
              <p className="text-base leading-8 text-[#eaecef] md:text-lg md:leading-9">{cleanHeadline}</p>
            </div>
          </div>
        </div>

        <div className="space-y-7 max-w-4xl">
          {cleanLead ? (
            <div className="relative pl-6 md:pl-10">
              <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-[#f0b90b] via-[rgba(240,185,11,0.3)] to-transparent" />
              <div className="absolute left-0 top-0 h-px w-4 bg-[#f0b90b]" />
              <div className="space-y-3">
                <h3
                  className="text-[9px] uppercase tracking-[0.16em] text-[#f0b90b]"
                  style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                >
                  핵심 인사이트
                </h3>
                <p className="text-sm leading-8 text-[#eaecef] md:text-base">{cleanLead}</p>
              </div>
            </div>
          ) : null}

          {cleanSupport ? (
            <div className="relative pl-6 md:pl-10">
              <div className="absolute left-0 top-0 h-full w-px bg-[#2b3139]" />
              <div className="space-y-3">
                <h3
                  className="text-[9px] uppercase tracking-[0.16em] text-[#474d57]"
                  style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                >
                  상세 맥락
                </h3>
                <p className="text-sm leading-8 text-[#848e9c]">{cleanSupport}</p>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
