"use client";

import React from "react";
import type { BriefMeta } from "@schema/brief.types";

import { formatIssueTime } from "@/lib/format";

type TerminalLine = {
  text: string;
  type: "SYSTEM" | "INFO" | "ANALYSIS";
  status?: string;
  tone?: "primary" | "success" | "warning";
};

function statusToneClass(tone?: TerminalLine["tone"]): string {
  if (tone === "success") {
    return "text-[var(--status-positive)]";
  }
  if (tone === "warning") {
    return "text-[var(--status-warning)]";
  }
  return "text-[var(--accent-primary)]";
}

export function TerminalPanel({
  meta,
  compact = false,
}: {
  meta: BriefMeta;
  compact?: boolean;
}) {
  const lines: TerminalLine[] = [
    { text: "system.intelligence — sovereign brief", type: "SYSTEM" },
    {
      text: `발행 기준일 ${meta.date} · 생성 시각 ${formatIssueTime(meta.generatedAt)} KST`,
      type: "INFO",
      status: "OK",
      tone: "primary",
    },
  ];

  return (
    <div
      className={`card-family-utility overflow-hidden rounded-[var(--card-radius-utility)] ${
        compact ? "min-h-[120px]" : "min-h-[140px]"
      }`}
    >
      <div className="flex items-center justify-between border-b border-white/6 bg-white/[0.02] px-4 py-2.5">
        <div className="flex gap-1.5">
          <span className="h-2 w-2 rounded-full bg-white/14" />
          <span className="h-2 w-2 rounded-full bg-white/14" />
          <span className="h-2 w-2 rounded-full bg-white/14" />
        </div>
        <p className="label-meta text-white/28">Intelligence Session</p>
        <span className="w-8" />
      </div>

      <div className={`space-y-2.5 p-4 font-mono ${compact ? "text-[11px]" : "text-[11.5px]"}`}>
        {lines.map((line) => (
          <div key={line.text} className="flex gap-2">
            {line.type === "SYSTEM" ? null : (
              <span
                className={`shrink-0 font-bold opacity-80 ${
                  line.type === "ANALYSIS"
                    ? "text-[var(--status-positive)]"
                    : "text-[var(--accent-primary)]"
                }`}
              >
                [{line.type}]
              </span>
            )}
            <span className={line.type === "SYSTEM" ? "italic text-white/44" : "text-white/88"}>
              {line.text}
              {line.status ? (
                <>
                  {" "}
                  <span className={`font-bold ${statusToneClass(line.tone)}`}>{line.status}</span>
                </>
              ) : null}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
