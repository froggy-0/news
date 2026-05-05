import type { XSignal } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { formatRelativeTime } from "@/lib/format";

const XIcon = ({ className = "" }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.134l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

function sentimentTone(value: XSignal["sentiment"]): string {
  if (value === "bullish") return "bg-[var(--accent-primary)]/20 text-[var(--accent-primary)]";
  if (value === "bearish") return "bg-[#ff6b6b]/18 text-[#ff6b6b]";
  return "bg-white/10 text-white/56";
}

function sentimentLabel(value: XSignal["sentiment"]): string {
  if (value === "bullish") return "상방";
  if (value === "bearish") return "하방";
  return "중립";
}

export function XSignalsList({
  items,
  showRawToggle = false,
  emptyMessage,
}: {
  items: XSignal[];
  showRawToggle?: boolean;
  emptyMessage: string;
}) {
  if (items.length === 0) {
    return <DataState title="X 시그널 상태" message={emptyMessage} family="reading" minHeight={220} />;
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
      {items.map((signal) => {
        const displayContent = signal.content?.trim() || signal.rawContent?.trim() || "";
        const rawContent = signal.rawContent?.trim();

        return (
          <article
            key={signal.id}
            className="card-signal card-family-reading group relative flex min-h-[240px] flex-col justify-between overflow-hidden rounded-[var(--card-radius-reading)] p-[var(--card-padding-reading)]"
          >
            <div
              className={`card-signal-line absolute left-0 top-0 h-0.5 w-full ${
                signal.sentiment === "bullish"
                  ? "bg-[var(--accent-primary)]/45"
                  : signal.sentiment === "bearish"
                    ? "bg-[#ff6b6b]/45"
                    : "bg-white/12"
              }`}
            />

            <div className="space-y-5">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-white/[0.03]">
                  <XIcon className="h-3.5 w-3.5 text-white/34" />
                </div>
                <span className="label-meta text-white/28">
                  Market Radar
                </span>
              </div>

              <p className="card-signal-copy text-[14px] leading-7 text-white/88 transition-colors group-hover:text-white">
                {displayContent}
              </p>
            </div>

            <div className="mt-6 space-y-3 border-t border-white/10 pt-5">
              <div>
                <span className="label-meta text-white/28">왜 중요한가</span>
                <p className="mt-2 text-[12px] leading-6 text-white/64">{signal.impact}</p>
              </div>

              <div className="label-meta flex flex-wrap items-center gap-x-3 gap-y-2 text-white/36">
                <span>{formatRelativeTime(signal.postedAt)}</span>
                <span className={`card-signal-pill rounded-full px-2 py-1 text-[8px] font-mono uppercase tracking-[0.16em] ${sentimentTone(signal.sentiment)}`}>
                  {sentimentLabel(signal.sentiment)}
                </span>
              </div>

              {showRawToggle && rawContent && rawContent !== displayContent ? (
                <details className="rounded-[16px] border border-white/8 bg-black/25 px-4 py-3">
                  <summary className="cursor-pointer text-[10px] font-mono uppercase tracking-[0.18em] text-white/42">
                    영문 원문 보기
                  </summary>
                  <p className="mt-3 text-sm leading-7 text-white/62">{rawContent}</p>
                </details>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}
