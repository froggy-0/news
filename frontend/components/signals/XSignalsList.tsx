import type { XSignal } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { formatRelativeTime } from "@/lib/format";

const XIcon = ({ className = "" }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.134l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

function sentimentTone(value: XSignal["sentiment"]): string {
  if (value === "bullish") return "bg-[#00ffff]/20 text-[#00ffff]";
  if (value === "bearish") return "bg-[#ff6b6b]/18 text-[#ff6b6b]";
  return "bg-white/10 text-white/56";
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
    return <DataState message={emptyMessage} />;
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
      {items.map((signal) => {
        const displayContent = signal.content?.trim() || signal.rawContent?.trim() || "";
        const rawContent = signal.rawContent?.trim();

        return (
          <article
            key={signal.id}
            className="group relative flex min-h-[280px] flex-col justify-between overflow-hidden rounded-[22px] border border-white/10 bg-white/[0.02] p-6 transition-all duration-300 hover:bg-white/[0.04]"
          >
            <div
              className={`absolute left-0 top-0 h-0.5 w-full ${
                signal.sentiment === "bullish"
                  ? "bg-[#00ffff]/45"
                  : signal.sentiment === "bearish"
                    ? "bg-[#ff6b6b]/45"
                    : "bg-white/12"
              }`}
            />

            <div className="space-y-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/[0.04]">
                    <XIcon className="h-4 w-4 text-white/42" />
                  </div>
                  <div className="space-y-1">
                    <span className="text-xs font-bold tracking-tight text-white">Intelligence Node</span>
                    <span className="text-[10px] font-mono text-white/42">@x_intel</span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <span className="text-[9px] font-mono uppercase tracking-[0.18em] text-white/32">
                    {formatRelativeTime(signal.postedAt)}
                  </span>
                  <span className={`rounded-full px-2 py-1 text-[8px] font-mono uppercase tracking-[0.16em] ${sentimentTone(signal.sentiment)}`}>
                    {signal.sentiment}
                  </span>
                </div>
              </div>

              <p className="text-[13.5px] leading-7 text-white/88 transition-colors group-hover:text-white">
                {displayContent}
              </p>
            </div>

            <div className="mt-6 space-y-3 border-t border-white/10 pt-5">
              <div className="flex items-center gap-2">
                <div className="h-3 w-1 rounded-full bg-[#00ffff]/60" />
                <span className="text-[9px] font-mono uppercase tracking-[0.24em] text-white/32">
                  영향력 분석
                </span>
              </div>
              <p className="text-[12px] leading-6 text-white/60">{signal.impact}</p>
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
