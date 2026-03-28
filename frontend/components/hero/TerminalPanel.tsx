"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useInView } from "motion/react";

import type { BriefMeta } from "@schema/brief.types";

import { formatIssueTime, qualityLabel, translationLabel } from "@/lib/format";

type TerminalLine = {
  text: string;
  type: "SYSTEM" | "INFO" | "ANALYSIS";
  status?: string;
  tone?: "primary" | "success" | "warning";
};

function statusTone(tone?: TerminalLine["tone"]): string {
  if (tone === "success") {
    return "text-[#00ff66]";
  }
  if (tone === "warning") {
    return "text-[#ffd166]";
  }
  return "text-[#00ffff]";
}

export function TerminalPanel({ meta }: { meta: BriefMeta }) {
  const lines = useMemo<TerminalLine[]>(
    () => [
      { text: "system.intelligence — sovereign brief", type: "SYSTEM" },
      {
        text: `발행 기준일 ${meta.date} · 생성 시각 ${formatIssueTime(meta.generatedAt)} KST`,
        type: "INFO",
        status: "OK",
        tone: "primary",
      },
      {
        text: `뉴스 ${meta.sourceCounts.newsCandidates}건 / X ${meta.sourceCounts.xSignalCandidates}건 정합성 점검`,
        type: "INFO",
        status: qualityLabel(meta.dataQuality),
        tone: meta.dataQuality === "ok" ? "primary" : "warning",
      },
      {
        text: `번역 상태 ${translationLabel(meta.translationStatus)} · 원본 무결성 기준 유지`,
        type: "ANALYSIS",
        status: "ACTIVE",
        tone: meta.translationStatus === "failed" ? "warning" : "success",
      },
    ],
    [meta],
  );
  const [lineTexts, setLineTexts] = useState<string[]>(lines.map(() => ""));
  const [currentLineIndex, setCurrentLineIndex] = useState(-1);
  const [showPrompt, setShowPrompt] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, amount: 0.4 });

  useEffect(() => {
    if (!isInView || currentLineIndex !== -1) {
      return;
    }

    const timer = window.setTimeout(() => {
      setCurrentLineIndex(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [currentLineIndex, isInView]);

  useEffect(() => {
    if (currentLineIndex < 0 || currentLineIndex >= lines.length) {
      return;
    }

    const fullText = lines[currentLineIndex].text;
    let charIndex = 0;

    const interval = window.setInterval(() => {
      if (charIndex <= fullText.length) {
        setLineTexts((previous) => {
          const next = [...previous];
          next[currentLineIndex] = fullText.slice(0, charIndex);
          return next;
        });
        charIndex += 1;
        return;
      }

      window.clearInterval(interval);
      if (currentLineIndex < lines.length - 1) {
        window.setTimeout(() => setCurrentLineIndex((value) => value + 1), 150);
      } else {
        window.setTimeout(() => setShowPrompt(true), 400);
      }
    }, 15);

    return () => window.clearInterval(interval);
  }, [currentLineIndex, lines]);

  return (
    <div
      ref={containerRef}
      className="overflow-hidden border border-white/10 bg-black/45 shadow-[0_0_56px_rgba(0,0,0,0.72)] backdrop-blur-sm"
    >
      <div className="flex items-center justify-between border-b border-white/6 bg-white/[0.03] px-4 py-2">
        <div className="flex gap-1.5">
          <div className="h-2 w-2 rounded-full bg-white/12" />
          <div className="h-2 w-2 rounded-full bg-white/12" />
          <div className="h-2 w-2 rounded-full bg-white/12" />
        </div>
        <div className="text-[9px] font-mono uppercase tracking-[0.3em] text-white/20">Terminal Session</div>
        <div className="w-10" />
      </div>
      <div className="min-h-[170px] space-y-2 p-6 font-mono text-[11px] leading-relaxed">
        {lines.map((line, index) => (
          <div
            key={`${line.text}-${index}`}
            className={`flex gap-2 transition-opacity duration-300 ${currentLineIndex >= index ? "opacity-100" : "opacity-0"}`}
          >
            {line.type === "SYSTEM" ? null : (
              <span className={`${line.type === "ANALYSIS" ? "text-[#00ff66]" : "text-[#00ffff]"} shrink-0 font-bold opacity-80`}>
                [{line.type}]
              </span>
            )}
            <span className={line.type === "SYSTEM" ? "italic text-white/40" : "text-white/90"}>
              {lineTexts[index]}
              {currentLineIndex === index && lineTexts[index].length < line.text.length ? (
                <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-white/40" />
              ) : null}
              {currentLineIndex >= index &&
              lineTexts[index].length === line.text.length &&
              line.status ? (
                <span className={`ml-2 animate-[fadeIn_0.2s_ease-out_forwards] font-bold opacity-0 ${statusTone(line.tone)}`}>
                  {line.status}
                </span>
              ) : null}
            </span>
          </div>
        ))}
        {showPrompt ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-4 flex items-center gap-1.5 border-t border-white/5 pt-4"
          >
            <span className="font-bold tracking-tighter text-[#00ffff]">›</span>
            <span className="text-[10px] uppercase tracking-[0.28em] text-white/40">Intelligence Stream Active</span>
            <motion.span
              animate={{ opacity: [1, 0] }}
              transition={{ duration: 0.8, repeat: Infinity }}
              className="h-3 w-1.5 bg-[#00ffff]/70"
            />
          </motion.div>
        ) : null}
      </div>
    </div>
  );
}
