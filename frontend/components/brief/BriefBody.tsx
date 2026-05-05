import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const EXCLUDED_SECTIONS = new Set(["0", "1", "2", "3", "4-1", "4-2", "4-3", "5-1", "5-2", "5-3", "6"]);
const SECTION_HEADER_RE = /^(\d+(?:-\d+)?)\.\s*/;
const MACHINE_PAYLOAD_RE = /^\s*[\[{].*[:].*[\]}]\s*$/;
const HANGUL_RE = /[가-힣]/;
const AS_OF_LINE_RE = /^\(?as of\s+/i;
const DATA_QUALITY_STATUS_RE = /^데이터 품질 상태:\s*(?:ok|degraded|critical)\s*$/i;
const BODY_REPLACEMENTS: Array<[RegExp, string]> = [
  [/BTC\s*&\s*크립토/gi, "비트코인과 크립토"],
  [/Big\s+Tech/gi, "크립토 기반"],
];

export function sanitizePublicBody(body: string): string {
  const lines = body.replace(/\r\n/g, "\n").split("\n");
  const kept: string[] = [];
  let excludeSection = false;

  for (const line of lines) {
    const stripped = line.trim();
    const sectionMatch = stripped.match(SECTION_HEADER_RE);
    if (sectionMatch) {
      excludeSection = EXCLUDED_SECTIONS.has(sectionMatch[1]);
      if (excludeSection) {
        continue;
      }
    }

    if (excludeSection) {
      continue;
    }
    if (stripped && AS_OF_LINE_RE.test(stripped)) {
      continue;
    }
    if (stripped && DATA_QUALITY_STATUS_RE.test(stripped)) {
      continue;
    }
    if (stripped && (MACHINE_PAYLOAD_RE.test(stripped) || stripped.startsWith("{'") || stripped.startsWith('{"'))) {
      continue;
    }
    if (stripped && !HANGUL_RE.test(stripped) && /[A-Za-z]/.test(stripped) && stripped.split(/\s+/).length >= 7) {
      continue;
    }
    const normalized = BODY_REPLACEMENTS.reduce(
      (accumulator, [pattern, replacement]) => accumulator.replace(pattern, replacement),
      line,
    );
    kept.push(normalized);
  }

  return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function BriefBody({
  body,
}: {
  body: string;
  date: string;
}) {
  const sanitizedBody = sanitizePublicBody(body);

  return (
    <section className="border-b border-white/10 px-6 py-20">
      <div className="mx-auto flex w-full max-w-6xl flex-col">
        <div className="section-shell rounded-[28px] p-6 md:p-8">
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{sanitizedBody}</ReactMarkdown>
          </div>
        </div>
      </div>
    </section>
  );
}
