import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { MarkdownDownloadButton } from "@/components/ui/MarkdownDownloadButton";

const EXCLUDED_SECTIONS = new Set(["1", "2", "3", "4-1", "4-2", "4-3", "5-1", "5-2", "5-3", "6"]);
const SECTION_HEADER_RE = /^(\d+(?:-\d+)?)\.\s*/;
const MACHINE_PAYLOAD_RE = /^\s*[\[{].*[:].*[\]}]\s*$/;
const HANGUL_RE = /[가-힣]/;
const BODY_REPLACEMENTS: Array<[RegExp, string]> = [
  [/BTC\s*&\s*크립토/gi, "비트코인과 크립토"],
  [/Big Tech/gi, "빅테크"],
];

function sanitizePublicBody(body: string): string {
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
    if (stripped && (MACHINE_PAYLOAD_RE.test(stripped) || stripped.startsWith("{'") || stripped.startsWith('{"'))) {
      continue;
    }
    if (stripped && !HANGUL_RE.test(stripped) && /[A-Za-z]/.test(stripped) && stripped.split(/\s+/).length >= 7) {
      continue;
    }
    const normalized = BODY_REPLACEMENTS.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), line);
    kept.push(normalized);
  }

  return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function BriefBody({
  body,
  date,
}: {
  body: string;
  date: string;
}) {
  const sanitizedBody = sanitizePublicBody(body);

  return (
    <section className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-6 flex flex-col gap-4 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">전체 발행본</p>
          <h2 className="display-headline mt-4 text-[2.15rem] md:text-[3.1rem]">브리핑 본문</h2>
          <p className="hero-support mt-3 max-w-2xl">
            홈에서 먼저 본 시장 카드와 중복되는 수치 블록은 덜어내고, 판단의 근거와 전체 발행 맥락을 읽게 합니다.
          </p>
        </div>
        <MarkdownDownloadButton body={body} date={date} />
      </div>
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{sanitizedBody}</ReactMarkdown>
      </div>
    </section>
  );
}
