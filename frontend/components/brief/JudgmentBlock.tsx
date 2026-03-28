import React from "react";

import { displayHeadline, formatIssueTime, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

export function JudgmentBlock({
  headline,
  summaryLead,
  summarySupport,
  issueDate,
  generatedAt,
  variant = "detail",
}: {
  headline: string;
  summaryLead: string;
  summarySupport: string | null;
  issueDate: string;
  generatedAt: string;
  variant?: "home" | "detail";
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
    <section id="brief" className={`${variant === "home" ? "px-6 py-16" : "border-b border-white/10 px-6 py-16"}`}>
      <div className={`mx-auto w-full ${variant === "home" ? "max-w-4xl" : "max-w-6xl"} space-y-12`}>
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3 text-[10px] font-mono uppercase tracking-[0.36em] text-white/40">
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-1.5 rounded-full bg-[#00ff66] shadow-[0_0_10px_rgba(0,255,102,0.65)]" />
              <span className="font-bold text-white/62">실시간 인텔리전스</span>
            </div>
            <span className="h-1 w-1 rounded-full bg-white/10" />
            <span>{formatPublicationDate(issueDate)}</span>
            <span className="h-1 w-1 rounded-full bg-white/10" />
            <span>{formatIssueTime(generatedAt)} KST</span>
          </div>
          <h2 className={variant === "home" ? "display-headline" : "display-headline max-w-5xl"}>
            {cleanHeadline}
          </h2>
        </div>

        <div className={`space-y-8 ${variant === "detail" ? "max-w-4xl" : ""}`}>
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
