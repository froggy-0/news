import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { MarkdownDownloadButton } from "@/components/ui/MarkdownDownloadButton";

export function BriefBody({
  body,
  date,
}: {
  body: string;
  date: string;
}) {
  return (
    <section className="panel rounded-[32px] px-6 py-7 md:px-8">
      <div className="mb-6 flex flex-col gap-4 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">브리핑</p>
          <h2 className="display-headline mt-4 text-3xl md:text-5xl">브리핑 본문</h2>
          <p className="hero-support mt-3 max-w-2xl">파이프라인이 생성한 본문을 그대로 보여주되, 읽는 리듬은 에디토리얼 지면처럼 정리합니다.</p>
        </div>
        <MarkdownDownloadButton body={body} date={date} />
      </div>
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
      </div>
    </section>
  );
}
